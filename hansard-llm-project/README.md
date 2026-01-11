# Tasmania Parliament Hansard LLM Training Project

## Project Overview

This project aims to build and train an LLM on Tasmania Parliament Hansard transcripts spanning from 1979 to present.

## Data Sources

Based on research, Tasmania Parliament Hansard has the following coverage:

- **1992-Present**: Available online via search portal at https://search.parliament.tas.gov.au/
- **1979-1991**: Historical archive digitized in 2015 (12 years of records, OCR-processed)
- **Pre-1979**: No official Hansard records (only newspaper reports)

### Key URLs
- Main Hansard page: https://www.parliament.tas.gov.au/hansard
- Search portal: https://search.parliament.tas.gov.au/
- PDF examples follow pattern: `https://www.parliament.tas.gov.au/__data/assets/pdf_file/[ID]/[filename].pdf`

## Project Pipeline

### Phase 1: Data Collection (PDF Download)

**Challenges:**
- Website has 403 protection against automated scraping
- PDFs are organized by sitting day, house (Assembly vs Council), and year
- Need to discover all PDF URLs across ~46 years of records

**Solutions:**
1. **Browser automation** using Selenium/Playwright to bypass 403 errors
2. **Sitemap exploration** if available
3. **Search API reverse engineering** from the search portal
4. **Manual initial mapping** then automated bulk download
5. **Rate limiting** to be respectful to parliament servers

**Estimated volume:**
- ~200-250 sitting days per year × 46 years = ~10,000 PDFs
- Each PDF typically 50-200 pages
- Total storage: ~50-100GB raw PDFs

### Phase 2: Text Extraction

**Tools:**
- PyPDF2 or pdfplumber for structured PDFs
- OCR (Tesseract/EasyOCR) for older scanned documents (1979-1991)
- pdf2text for simple extraction

**Challenges:**
- OCR quality issues in 1979-1991 archives
- Different PDF formats across decades
- Headers, footers, page numbers need removal
- Multi-column layouts in some documents

### Phase 3: Text Cleaning & Preprocessing

**Required cleaning:**
1. Remove headers/footers (dates, page numbers, "DRAFT HANSARD")
2. Normalize speaker labels: `[Member Name]:` format
3. Remove administrative text (procedural notes, interruptions)
4. Fix OCR errors in historical documents
5. Standardize formatting (paragraphs, line breaks)
6. Handle special parliamentary language/procedures
7. Preserve structure: speaker turns, questions, answers, debates

**Data structure:**
```json
{
  "date": "2025-12-04",
  "house": "House of Assembly",
  "speakers": [
    {
      "name": "Member Name",
      "role": "Minister/Member",
      "text": "Speech content..."
    }
  ],
  "topics": ["Budget", "Healthcare"],
  "metadata": {
    "session_number": "...",
    "pdf_source": "..."
  }
}
```

### Phase 4: LLM Training Strategy

**Approach Options:**

#### Option A: Fine-tuning an Existing Model (Recommended)
- **Base model**: LLama 3, Mistral, or GPT (via API)
- **Method**: LoRA/QLoRA for efficiency
- **Dataset size**: 100M-500M tokens (estimated from Hansard corpus)
- **Training time**: Days to weeks depending on hardware
- **Cost**: $500-$5000 for cloud GPU (A100/H100)

#### Option B: RAG (Retrieval-Augmented Generation)
- **Simpler alternative**: No model training required
- **Vector database**: Store Hansard chunks in Pinecone/Weaviate/ChromaDB
- **Embedding model**: sentence-transformers or OpenAI embeddings
- **Query time**: Retrieve relevant passages, feed to LLM
- **Cost**: Lower upfront, pay per query

#### Option C: Pre-training from Scratch
- **Not recommended**: Requires massive compute (millions of dollars)
- **Only if**: Building foundation model for Australian parliamentary language

**Recommended: Fine-tuning with LoRA**
- Training data: ~200M tokens (cleaned Hansard text)
- Format: Instruction-following dataset
- Tasks: Q&A, summarization, speaker attribution, topic extraction
- Hardware: Single A100 (40GB) or multiple consumer GPUs

### Phase 5: Model Capabilities

**Target use cases:**
1. Question-answering about parliamentary debates
2. Summarizing debates on specific topics
3. Tracking legislative history
4. Analyzing member voting patterns and positions
5. Generating debate transcripts in parliamentary style
6. Identifying policy evolution over decades

## Technical Requirements

### Software Dependencies
```
- Python 3.9+
- selenium/playwright (web scraping)
- PyPDF2/pdfplumber (PDF extraction)
- pytesseract (OCR for old documents)
- transformers, peft (HuggingFace for LLM fine-tuning)
- datasets (HuggingFace dataset management)
- accelerate, bitsandbytes (efficient training)
- langchain (optional, for RAG)
- chromadb/pinecone (optional, vector storage)
```

### Hardware Requirements

**For data collection & processing:**
- Standard laptop/desktop sufficient
- 200GB+ storage for PDFs and processed text

**For LLM training:**
- GPU: NVIDIA A100 (40GB) or 4x RTX 4090
- RAM: 64GB+
- Storage: 500GB SSD
- OR cloud: AWS/GCP/Lambda Labs GPU instances

## Timeline Estimate

- **Phase 1 (Download)**: 1-2 weeks (including rate limiting)
- **Phase 2 (Extraction)**: 1 week
- **Phase 3 (Cleaning)**: 2-3 weeks (iterative process)
- **Phase 4 (Training)**: 1-2 weeks (preparation + training)
- **Phase 5 (Evaluation)**: 1-2 weeks

**Total**: 2-3 months for complete pipeline

## Ethical & Legal Considerations

1. **Copyright**: Parliamentary proceedings are typically Crown Copyright but publicly available
2. **Rate limiting**: Be respectful to parliament servers (1-2 second delays)
3. **Attribution**: Properly cite Tasmania Parliament as data source
4. **Use case**: Ensure model use aligns with public interest

## Next Steps

1. Manual exploration of search.parliament.tas.gov.au to understand URL patterns
2. Build proof-of-concept downloader for recent PDFs (2024-2025)
3. Extract and analyze 10-20 sample PDFs to understand formats
4. Develop cleaning pipeline for sample data
5. Decide on fine-tuning vs RAG approach
6. Scale to full dataset

## Resources

- Tasmania Parliament Hansard: https://www.parliament.tas.gov.au/hansard
- Search Portal: https://search.parliament.tas.gov.au/
- State Library Victoria Guide: https://guides.slv.vic.gov.au/tasgovpubs/hansard
