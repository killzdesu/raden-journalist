import asyncio
import logging
import argparse
import json
from database.db import init_db, save_article, log_run, get_unsent_articles, mark_article_sent, get_unsummarized_articles, save_summary, update_article_type
from fetchers.pubmed import fetch_recent_articles
from processors.filter import filter_new_articles
from summarizer.llm import summarize_article, check_articles_relevance_batch, classify_article_type
from notifier.discord import send_header, send_article
from config import MAX_ARTICLES_PER_RUN


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

async def main():
    parser = argparse.ArgumentParser(description="Research Digest Bot")
    parser.add_argument("--no-fetch", action="store_true", help="Process unsent articles from queue without fetching new ones")
    parser.add_argument("--summarize-only", action="store_true", help="Only summarize unsummarized articles in the queue")
    parser.add_argument("--send-new-only", action="store_true", help="Only send summarized but unsent articles")
    args = parser.parse_args()

    logging.info("Starting Research Digest Run")
    init_db()
    
    try:
        all_articles_count = 0
        sent_count = 0

        # Step 1: Fetching
        if not args.no_fetch and not args.summarize_only and not args.send_new_only:
            
            # 1. Fetch Allergy Journals
            logging.info("Fetching articles from PubMed (Allergy Pool)...")
            allergy_articles = await fetch_recent_articles()
            all_articles_count += len(allergy_articles)
            new_allergy_articles = filter_new_articles(allergy_articles)
            new_allergy_articles = [a for a in new_allergy_articles if a.get("abstract") and a.get("abstract").strip()]
            logging.info(f"Found {len(allergy_articles)} raw allergy articles. After deduplication and abstract check: {len(new_allergy_articles)} new articles to process.")
            
            # Save new allergy articles to queue
            for article in new_allergy_articles:
                save_article(
                    pmid=article["pmid"],
                    doi=article.get("doi", ""),
                    title=article.get("title", ""),
                    journal=article.get("journal", ""),
                    pub_date=article.get("pub_date", ""),
                    abstract=article.get("abstract", ""),
                    authors=article.get("authors", ""),
                    article_type=article.get("article_type", ""),
                    journal_pool="Q1 Allergy"
                )
            
            # 2. Fetch Non-Allergy Journals (DISABLED FOR NOW)
            # non_allergy_issns = []
            # try:
            #     with open("non-allergy-pool.json", "r") as f:
            #         non_allergy_pool = json.load(f)
            #     non_allergy_issns = [j["online_issn"] for j in non_allergy_pool if "online_issn" in j]
            # except Exception as e:
            #     logging.error(f"Failed to load non-allergy pool metadata: {e}")
            #
            # if non_allergy_issns:
            #     logging.info("Fetching articles from PubMed (Non-Allergy Pool)...")
            #     non_allergy_articles = await fetch_recent_articles(non_allergy_issns)
            #     all_articles_count += len(non_allergy_articles)
            #     new_non_allergy_articles = filter_new_articles(non_allergy_articles)
            #     logging.info(f"Found {len(non_allergy_articles)} raw non-allergy articles. After deduplication: {len(new_non_allergy_articles)} new articles to process.")
            #     
            #     # Check Relevance in Batches
            #     relevant_non_allergy = []
            #     batch_size = 15
            #     
            #     for i in range(0, len(new_non_allergy_articles), batch_size):
            #         batch = new_non_allergy_articles[i:i+batch_size]
            #         logging.info(f"Relevance check batch {i//batch_size + 1}/{(len(new_non_allergy_articles) + batch_size - 1)//batch_size}: processing {len(batch)} articles...")
            #         
            #         relevant_pmids = await check_articles_relevance_batch(batch)
            #         
            #         # Add wait to avoid rate limit
            #         await asyncio.sleep(2.0)
            #         
            #         # Filter batch
            #         for article in batch:
            #             if article["pmid"] in relevant_pmids:
            #                 relevant_non_allergy.append(article)
            #     
            #     logging.info(f"New Non-Allergy Articles after relevance validation: {len(relevant_non_allergy)}")
            #     
            #     # Save non allergy articles
            #     for article in relevant_non_allergy:
            #         save_article(
            #             pmid=article["pmid"],
            #             doi=article.get("doi", ""),
            #             title=article.get("title", ""),
            #             journal=article.get("journal", ""),
            #             pub_date=article.get("pub_date", ""),
            #             abstract=article.get("abstract", ""),
            #             authors=article.get("authors", ""),
            #             article_type=article.get("article_type", ""),
            #             journal_pool="non allergy"
            #         )
            
            logging.info("Saved all new relevant articles to queue.")
        else:
            logging.info("Skipping fetch phase.")

        # Step 2: Summarizing
        if not args.send_new_only:
            unsummarized = get_unsummarized_articles(MAX_ARTICLES_PER_RUN)
            if unsummarized:
                logging.info(f"Summarizing {len(unsummarized)} articles...")
                for article in unsummarized:
                    logging.info(f"Summarizing PMID: {article['pmid']}")
                    summary = await summarize_article(article)
                    if summary:
                        save_summary(article["pmid"], summary)
                        
                        logging.info(f"Classifying article type for PMID: {article['pmid']}")
                        article_type = await classify_article_type(article, summary)
                        if article_type:
                            update_article_type(article["pmid"], article_type)
                            logging.info(f"Classified PMID: {article['pmid']} as {article_type}")
                    else:
                        logging.warning(f"Failed to generate summary for PMID: {article['pmid']}")
                        
                # Check LLM output logic
                still_unsummarized = get_unsummarized_articles(MAX_ARTICLES_PER_RUN)
                failed_pmids = [a['pmid'] for a in still_unsummarized if a['pmid'] in [u['pmid'] for u in unsummarized]]
                if failed_pmids:
                    logging.warning(f"Some articles failed to summarize and are still missing summaries: {failed_pmids}")
            else:
                logging.info("No unsummarized articles found.")
        else:
            logging.info("Skipping summarize phase.")

        # Step 3: Sending
        if not args.summarize_only:
            queued_articles = get_unsent_articles(MAX_ARTICLES_PER_RUN)
            
            if not queued_articles:
                logging.info("No unsent articles in queue.")
            else:
                logging.info(f"Sending {len(queued_articles)} articles from queue.")
                await send_header(len(queued_articles))
                await asyncio.sleep(1.5) # Initial delay
                
                for article in queued_articles:
                    logging.info(f"Sending PMID: {article['pmid']}")
                    
                    summary = article.get("summary", "No summary available.")
                    
                    # Send to Discord
                    await send_article(article, summary)
                    
                    # Mark as sent
                    mark_article_sent(article["pmid"])
                    
                    sent_count += 1
                    await asyncio.sleep(1.5) # Standard Discord webhook tolerance
        else:
            logging.info("Skipping send phase.")
            
        status = "success"
        if args.no_fetch or args.summarize_only or args.send_new_only:
            status += " (partial run)"
        log_run(all_articles_count, sent_count, status)
        
        logging.info(f"Run complete. Fetched: {all_articles_count}, Sent: {sent_count}.")
        
    except Exception as e:
        logging.error(f"Fatal run error: {e}", exc_info=True)
        log_run(0, 0, f"error: {str(e)[:50]}")
        
    finally:
        from config import LOG_SIZE_LIMIT_MB
        import os
        
        # Safely shut down logging so we can modify the file
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)
            
        log_file = "bot.log"
        if os.path.exists(log_file):
            limit_bytes = LOG_SIZE_LIMIT_MB * 1024 * 1024
            if os.path.getsize(log_file) > limit_bytes:
                try:
                    with open(log_file, 'rb') as f:
                        content = f.read()
                    
                    truncated = content[-limit_bytes:]
                    newline_pos = truncated.find(b'\n')
                    if newline_pos != -1:
                        truncated = truncated[newline_pos+1:]
                        
                    with open(log_file, 'wb') as f:
                        f.write(truncated)
                except Exception:
                    pass

if __name__ == "__main__":
    asyncio.run(main())
