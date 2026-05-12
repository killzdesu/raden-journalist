import logging
from database.db import article_exists

def filter_new_articles(articles):
    """Filter out articles that already exist in the database."""
    new_articles = []
    for article in articles:
        pmid = article.get("pmid")
        doi = article.get("doi", "")
        if not pmid:
            logging.warning("Article without PMID found, skipping.")
            continue
            
        if not article_exists(pmid, doi):
            new_articles.append(article)
        else:
            logging.debug(f"Article {pmid} already processed. Skipping.")
            
    return new_articles
