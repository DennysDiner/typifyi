# Quick Start Guide - Tasmania Parliament Hansard LLM Training

This guide will walk you through the complete pipeline from downloading PDFs to training an LLM.

## Prerequisites

### System Requirements
- Python 3.9 or higher
- 200GB+ free disk space (for PDFs and processed data)
- CUDA-capable GPU with 8GB+ VRAM (for training)
  - Or access to cloud GPU (AWS, GCP, Lambda Labs, RunPod)

### Software Dependencies
- Chrome/Chromium browser (for Selenium)
- Tesseract OCR (for scanned documents)
- CUDA toolkit (for GPU training)

## Installation

### 1. Clone/Navigate to Project Directory

```bash
cd hansard-llm-project
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr chromium-chromedriver poppler-utils
```

**macOS:**
```bash
brew install tesseract poppler
brew install --cask chromedriver
```

**Windows:**
- Download Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
- Download ChromeDriver: https://chromedriver.chromium.org/

## Pipeline Steps

### Step 1: Explore and Discover PDFs

First, explore the Tasmania Parliament website to understand the structure:

```bash
python 1_download_pdfs.py --explore --output-dir ./pdfs
```

This will:
- Navigate to the Parliament website
- Discover available PDF links
- Save them to `discovered_urls_*.txt` files

### Step 2: Download PDFs

**Option A: From discovered URLs**
```bash
python 1_download_pdfs.py --url-list ./pdfs/discovered_urls_*.txt --output-dir ./pdfs --delay 2.0
```

**Option B: Manual URL list**
Create a file `url_list.txt` with one PDF URL per line, then:
```bash
python 1_download_pdfs.py --url-list url_list.txt --output-dir ./pdfs
```

**Tips:**
- Start with recent years (2020-2025) to test the pipeline
- Use `--delay 2.0` to be respectful to the server (2 second delay between requests)
- The script saves progress, so you can resume if interrupted

### Step 3: Extract Text from PDFs

```bash
python 2_extract_text.py --pdf-dir ./pdfs --output-dir ./extracted_text --structure
```

This will:
- Detect whether PDFs are digital or scanned
- Use appropriate extraction method (pdfplumber for modern, OCR for old)
- Save raw text to `./extracted_text/raw_text/`
- Create structured JSON to `./extracted_text/structured_json/`

**For specific year ranges:**
```bash
python 2_extract_text.py --pdf-dir ./pdfs --pattern "*2024*.pdf" --output-dir ./extracted_text
```

**Force OCR for all files (if extraction quality is poor):**
```bash
python 2_extract_text.py --pdf-dir ./pdfs --force-ocr --output-dir ./extracted_text
```

### Step 4: Clean and Preprocess Text

```bash
python 3_clean_and_preprocess.py \
    --input-dir ./extracted_text \
    --output-dir ./cleaned_data \
    --create-training \
    --format jsonl \
    --instruction-dataset
```

This will:
- Remove headers, footers, and page numbers
- Fix OCR errors
- Normalize speaker labels
- Create training dataset in JSONL format
- Generate instruction-following examples

Output files:
- `./cleaned_data/cleaned_text/` - Cleaned text files
- `./cleaned_data/training_data/hansard_training.jsonl` - Training dataset
- `./cleaned_data/training_data/hansard_instructions.jsonl` - Instruction dataset

### Step 5: Train the LLM

**Small test run (recommended first):**
```bash
python 4_train_llm.py \
    --base-model "meta-llama/Llama-3-8b" \
    --data-file ./cleaned_data/training_data/hansard_training.jsonl \
    --output-dir ./models/hansard-llm-test \
    --epochs 1 \
    --batch-size 2 \
    --max-length 1024
```

**Full training run:**
```bash
python 4_train_llm.py \
    --base-model "meta-llama/Llama-3-8b" \
    --data-file ./cleaned_data/training_data/hansard_training.jsonl \
    --output-dir ./models/hansard-llm \
    --epochs 3 \
    --batch-size 4 \
    --learning-rate 2e-4 \
    --lora-r 16 \
    --use-4bit \
    --use-wandb \
    --test-prompt "What did the Minister discuss about healthcare?"
```

**Alternative base models:**
- `"mistralai/Mistral-7B-v0.1"` - Excellent for instruction following
- `"microsoft/phi-2"` - Smaller, faster training
- `"meta-llama/Llama-2-13b"` - Larger, better performance

**Training options:**
- `--use-4bit`: Reduces VRAM usage significantly (recommended)
- `--use-wandb`: Track experiments with Weights & Biases
- `--lora-r`: LoRA rank (8-64; lower=faster, higher=better quality)

### Step 6: Use the Trained Model

After training, use the model for inference:

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# Load base model
base_model = AutoModelForCausalLM.from_pretrained("meta-llama/Llama-3-8b")
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3-8b")

# Load LoRA adapter
model = PeftModel.from_pretrained(base_model, "./models/hansard-llm")

# Generate
prompt = "What legislation was discussed regarding education in 2024?"
inputs = tokenizer(prompt, return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=200)
print(tokenizer.decode(outputs[0]))
```

## Alternative Approach: RAG (No Training Required)

If you want to query the Hansard data without training a model, use RAG:

```python
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma
from langchain.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Load cleaned text
loader = TextLoader("./cleaned_data/cleaned_text/")
documents = loader.load()

# Split into chunks
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
chunks = text_splitter.split_documents(documents)

# Create embeddings
embeddings = HuggingFaceEmbeddings()

# Create vector store
vectorstore = Chroma.from_documents(chunks, embeddings)

# Query
query = "What was discussed about healthcare in 2024?"
results = vectorstore.similarity_search(query, k=5)
```

## Troubleshooting

### Issue: 403 Errors When Downloading
- The website has anti-bot protection
- Use the `--explore` mode first to understand structure
- Consider manual download of a sample set first
- Increase `--delay` to 3-5 seconds

### Issue: OCR Quality Poor
- Install latest Tesseract: `sudo apt-get install tesseract-ocr-eng`
- Increase DPI in `2_extract_text.py` (line: `convert_from_path(pdf_path, dpi=300)` → `dpi=400`)
- Try different OCR engines (EasyOCR instead of Tesseract)

### Issue: Out of Memory During Training
- Reduce `--batch-size` to 1 or 2
- Enable `--use-4bit` quantization
- Reduce `--max-length` to 512 or 1024
- Use gradient checkpointing (enabled by default)
- Use smaller base model (phi-2 instead of Llama)

### Issue: Training is Slow
- Use cloud GPU (Lambda Labs ~$0.50/hour for A100)
- Reduce dataset size for initial testing
- Lower `--lora-r` to 8 (faster training, slightly lower quality)

## Cost Estimates

### DIY with Cloud GPU (Recommended)
- Lambda Labs A100 (40GB): $1.10/hour
- Training time: ~8-24 hours for full dataset
- **Total: $10-30**

### AWS/GCP
- AWS p3.2xlarge (V100): $3.06/hour
- Training time: ~12-48 hours
- **Total: $40-150**

### Local GPU
- RTX 4090: Free (if you have one)
- Training time: ~24-72 hours
- Electricity: ~$5-15

## Next Steps

1. **Start small**: Test with 2024-2025 data only
2. **Evaluate**: Check text extraction quality before scaling
3. **Iterate**: Adjust cleaning rules based on sample outputs
4. **Scale up**: Once pipeline works, process full 1979-2025 dataset
5. **Fine-tune**: Train on complete dataset
6. **Deploy**: Create API or web interface for querying

## Resources

- [LoRA Paper](https://arxiv.org/abs/2106.09685)
- [HuggingFace Transformers](https://huggingface.co/docs/transformers)
- [PEFT Library](https://github.com/huggingface/peft)
- [LangChain RAG](https://python.langchain.com/docs/use_cases/question_answering/)

## Support

For issues or questions about this project:
1. Check the main README.md
2. Review error logs in each script's output
3. Test with smaller datasets first

Good luck building your Hansard LLM!
