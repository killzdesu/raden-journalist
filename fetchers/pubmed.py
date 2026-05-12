import httpx
import xml.etree.ElementTree as ET
import logging
from datetime import datetime, timedelta

from config import NCBI_API_KEY, TARGET_JOURNALS, LOOKBACK_DAYS

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def build_search_query(target_journals=None):
    if target_journals is None:
        target_journals = TARGET_JOURNALS
    # Build journal OR part using ISSN
    journals = " OR ".join([f'"{issn}"[IS]' for issn in target_journals])
    
    # Dates
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    date_range = f'("{start_date.strftime("%Y/%m/%d")}"[PDAT] : "{end_date.strftime("%Y/%m/%d")}"[PDAT])'
    
    # Types (Excluding non-research types directly in query)
    exclusions = 'NOT (Letter[ptyp] OR Comment[ptyp] OR Editorial[ptyp] OR Erratum[ptyp] OR "Case Reports"[ptyp])'
    # Language: English
    lang = 'English[LA]'
    
    query = f"({journals}) AND {date_range}" # AND {exclusions} AND {lang}"
    return query

async def fetch_recent_articles(target_journals=None):
    query = build_search_query(target_journals)
    
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": 100,
        "sort": "date"
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
        
    async with httpx.AsyncClient() as client:
        try:
            search_resp = await client.get(f"{BASE_URL}/esearch.fcgi", params=params, timeout=15.0)
            search_resp.raise_for_status()
            search_data = search_resp.json()
            
            pmids = search_data.get("esearchresult", {}).get("idlist", [])
            if not pmids:
                return []
                
            # Fetch detailed XML
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
            }
            if NCBI_API_KEY:
                fetch_params["api_key"] = NCBI_API_KEY
                
            fetch_resp = await client.get(f"{BASE_URL}/efetch.fcgi", params=fetch_params, timeout=30.0)
            fetch_resp.raise_for_status()
            
            return parse_pubmed_xml(fetch_resp.text)
            
        except Exception as e:
            logging.error(f"Error fetching from PubMed: {e}")
            return []

def parse_pubmed_xml(xml_content: str):
    articles = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logging.error(f"Failed to parse PubMed XML: {e}")
        return []

    for article_node in root.findall(".//PubmedArticle"):
        try:
            pmid = article_node.find(".//PMID").text
            title_node = article_node.find(".//ArticleTitle")
            title = "".join(title_node.itertext()) if title_node is not None else "No Title"
            
            abstract_nodes = article_node.findall(".//AbstractText")
            if not abstract_nodes:
                continue # Skip if no abstract
                
            abstract_parts = []
            for node in abstract_nodes:
                label = node.attrib.get("Label", "")
                text = "".join(node.itertext()).strip()
                if label:
                    abstract_parts.append(f"{label}: {text}")
                elif text:
                    abstract_parts.append(text)
            
            abstract = "\n".join(abstract_parts).strip()
            if not abstract:
                continue
                
            # Journal extraction
            journal = article_node.find(".//Title")
            journal_title = journal.text if journal is not None else "Unknown Journal"
            
            # DOI extraction
            doi = ""
            for eloc in article_node.findall(".//ELocationID"):
                if eloc.attrib.get("EIdType") == "doi":
                    doi = eloc.text
                    break
                    
            if not doi:
                for article_id in article_node.findall(".//ArticleId"):
                    if article_id.attrib.get("IdType") == "doi":
                        doi = article_id.text
                        break
                        
            # Publication Date
            pub_date = ""
            pub_date_node = article_node.find(".//PubDate")
            if pub_date_node is not None:
                year = pub_date_node.find("Year")
                month = pub_date_node.find("Month")
                day = pub_date_node.find("Day")
                
                parts = []
                if year is not None and year.text: parts.append(year.text)
                if month is not None and month.text: parts.append(month.text)
                if day is not None and day.text: parts.append(day.text)
                pub_date = " ".join(parts)
                
            # Authors
            authors = []
            for author_node in article_node.findall(".//Author"):
                last_name = author_node.find("LastName")
                initials = author_node.find("Initials")
                if last_name is not None and last_name.text:
                    name = last_name.text
                    if initials is not None and initials.text:
                        name += f" {initials.text}"
                    authors.append(name)
            
            authors_str = ", ".join(authors) if authors else "Unknown Authors"
            
            # Article Types
            article_types = []
            for ptype_node in article_node.findall(".//PublicationType"):
                if ptype_node.text:
                    article_types.append(ptype_node.text)
            
            article_type_str = ", ".join(article_types) if article_types else "Unknown Type"
            
            articles.append({
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "journal": journal_title,
                "doi": doi,
                "pub_date": pub_date,
                "authors": authors_str,
                "article_type": article_type_str
            })
        except Exception as e:
            logging.error(f"Error parsing article node: {e}")
            continue
            
    return articles
