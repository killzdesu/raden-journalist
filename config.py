import os
from dotenv import load_dotenv

load_dotenv()

# PubMed API settings
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

# LLM Providers
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

KKU_API_KEY = os.getenv("KKU_API_KEY")

BACKUP_LLM_PROVIDER = os.getenv("BACKUP_LLM_PROVIDER", "openrouter")
BACKUP_LLM_MODEL = os.getenv("BACKUP_LLM_MODEL", "openrouter/free")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# SIMPLE TASK LLM PROVIDER
SIMPLE_TASK_LLM_PROVIDER = os.getenv("SIMPLE_TASK_LLM_PROVIDER", "openrouter")
SIMPLE_TASK_LLM_MODEL = os.getenv("SIMPLE_TASK_LLM_MODEL", "openrouter/free")
SIMPLE_TASK_LLM_API_KEY = os.getenv("SIMPLE_TASK_LLM_API_KEY")

# Discord settings
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Application Settings
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "10"))
MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "3"))
LOG_SIZE_LIMIT_MB = int(os.getenv("LOG_SIZE_LIMIT_MB", "10"))

# Target Journals (Online ISSNs)
TARGET_JOURNALS = [
    "1097-6825", # JACI
    "2213-2201", # JACI: In Practice
    "1398-9995", # Allergy
    "1365-2222", # Clinical & Experimental Allergy
    "1942-3933", # Annals of Allergy, Asthma & Immunology
    "1399-3038", # Pediatric Allergy and Immunology
    "2045-7022", # Clinical and Translational Allergy
    "1939-4551", # World Allergy Organization Journal
    "2673-6101", # Frontiers in Allergy
    "2092-7363", # Allergy, Asthma & Immunology Research
]
