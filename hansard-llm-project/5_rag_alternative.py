#!/usr/bin/env python3
"""
Tasmania Parliament Hansard RAG (Retrieval-Augmented Generation)

This script provides a simpler alternative to fine-tuning: using RAG to query
Hansard data without training a model. This is faster to set up and cheaper
to run, though may have different performance characteristics.

Usage:
    python 5_rag_alternative.py --data-dir ./cleaned_data/cleaned_text --build-index
    python 5_rag_alternative.py --data-dir ./cleaned_data/cleaned_text --query "What was discussed about healthcare?"
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


class HansardRAG:
    def __init__(
        self,
        data_dir: str = "./cleaned_data/cleaned_text",
        index_dir: str = "./vector_index",
        embedding_model: str = "all-MiniLM-L6-v2"
    ):
        """
        Initialize the RAG system for Hansard documents.

        Args:
            data_dir: Directory containing cleaned text files
            index_dir: Directory to store vector index
            embedding_model: SentenceTransformer model to use for embeddings
        """
        self.data_dir = Path(data_dir)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Initialize embedding model
        print(f"Loading embedding model: {embedding_model}")
        self.embedding_model = SentenceTransformer(embedding_model)

        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(self.index_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="hansard",
            metadata={"description": "Tasmania Parliament Hansard documents"}
        )

    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """
        Split text into overlapping chunks.

        Args:
            text: Text to chunk
            chunk_size: Size of each chunk in characters
            overlap: Overlap between chunks

        Returns:
            List of text chunks
        """
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence ending
                sentence_end = text.rfind('.', start, end)
                if sentence_end > start:
                    end = sentence_end + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap

        return chunks

    def build_index(self, chunk_size: int = 1000, overlap: int = 200):
        """
        Build vector index from cleaned Hansard texts.

        Args:
            chunk_size: Size of text chunks
            overlap: Overlap between chunks
        """
        print(f"Building vector index from {self.data_dir}")

        text_files = list(self.data_dir.glob("*.txt"))
        print(f"Found {len(text_files)} documents")

        total_chunks = 0

        for i, text_file in enumerate(text_files, 1):
            print(f"[{i}/{len(text_files)}] Processing: {text_file.name}")

            # Read text
            with open(text_file, 'r', encoding='utf-8') as f:
                text = f.read()

            # Split into chunks
            chunks = self.chunk_text(text, chunk_size, overlap)
            print(f"  Created {len(chunks)} chunks")

            # Create embeddings (in batches to avoid memory issues)
            batch_size = 32
            for batch_start in range(0, len(chunks), batch_size):
                batch_end = min(batch_start + batch_size, len(chunks))
                batch_chunks = chunks[batch_start:batch_end]

                # Generate embeddings
                embeddings = self.embedding_model.encode(
                    batch_chunks,
                    show_progress_bar=False
                ).tolist()

                # Create IDs and metadata
                ids = [f"{text_file.stem}_chunk_{total_chunks + j}"
                      for j in range(len(batch_chunks))]

                metadatas = [{
                    "source": text_file.name,
                    "chunk_id": total_chunks + j,
                    "chunk_start": batch_start + j
                } for j in range(len(batch_chunks))]

                # Add to collection
                self.collection.add(
                    embeddings=embeddings,
                    documents=batch_chunks,
                    metadatas=metadatas,
                    ids=ids
                )

                total_chunks += len(batch_chunks)

        print(f"\nIndex built successfully!")
        print(f"Total chunks indexed: {total_chunks}")
        print(f"Index saved to: {self.index_dir}")

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Dict = None
    ) -> List[Dict]:
        """
        Search for relevant Hansard passages.

        Args:
            query: Search query
            n_results: Number of results to return
            filter_metadata: Optional metadata filters (e.g., {"source": "2024-12-04.txt"})

        Returns:
            List of search results with text and metadata
        """
        print(f"Searching for: '{query}'")

        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])[0].tolist()

        # Search
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filter_metadata
        )

        # Format results
        formatted_results = []
        for i in range(len(results['documents'][0])):
            formatted_results.append({
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i] if 'distances' in results else None
            })

        return formatted_results

    def query_with_llm(
        self,
        query: str,
        n_results: int = 3,
        llm_model: str = "gpt-3.5-turbo"
    ) -> str:
        """
        Query Hansard data and generate answer using an LLM.

        Args:
            query: User question
            n_results: Number of relevant passages to retrieve
            llm_model: LLM to use for answer generation

        Returns:
            Generated answer
        """
        # Retrieve relevant passages
        results = self.search(query, n_results=n_results)

        # Combine passages as context
        context_passages = [r['text'] for r in results]
        context = "\n\n---\n\n".join(context_passages)

        # Create prompt
        prompt = f"""You are an AI assistant helping to answer questions about Tasmania Parliament proceedings.

Based on the following excerpts from Hansard (parliamentary transcripts), answer the user's question.

Context from Hansard:
{context}

User question: {query}

Answer (provide specific information from the Hansard excerpts above):"""

        # Generate answer using LLM
        # This is a placeholder - you can integrate with OpenAI API, Anthropic API, or local LLM
        print("\n" + "="*60)
        print("RETRIEVED CONTEXT:")
        print("="*60)
        for i, result in enumerate(results, 1):
            print(f"\nPassage {i} (from {result['metadata']['source']}):")
            print(result['text'][:300] + "...")

        print("\n" + "="*60)
        print("PROMPT TO LLM:")
        print("="*60)
        print(prompt)

        # To actually generate an answer, uncomment and configure one of these:

        # Option 1: OpenAI
        # import openai
        # response = openai.ChatCompletion.create(
        #     model=llm_model,
        #     messages=[{"role": "user", "content": prompt}]
        # )
        # return response.choices[0].message.content

        # Option 2: Anthropic Claude
        # import anthropic
        # client = anthropic.Anthropic()
        # response = client.messages.create(
        #     model="claude-3-sonnet-20240229",
        #     messages=[{"role": "user", "content": prompt}]
        # )
        # return response.content[0].text

        # Option 3: Local LLM (ollama)
        # import requests
        # response = requests.post('http://localhost:11434/api/generate', json={
        #     'model': 'llama2',
        #     'prompt': prompt
        # })
        # return response.json()['response']

        return "[Configure LLM API to generate answer - see comments in code]"

    def get_stats(self):
        """Get statistics about the indexed documents."""
        count = self.collection.count()
        print(f"Total indexed chunks: {count}")
        return {"total_chunks": count}


def main():
    parser = argparse.ArgumentParser(description='Hansard RAG System')
    parser.add_argument('--data-dir', type=str, default='./cleaned_data/cleaned_text',
                       help='Directory containing cleaned text files')
    parser.add_argument('--index-dir', type=str, default='./vector_index',
                       help='Directory to store vector index')
    parser.add_argument('--embedding-model', type=str, default='all-MiniLM-L6-v2',
                       help='SentenceTransformer model for embeddings')
    parser.add_argument('--build-index', action='store_true',
                       help='Build vector index from documents')
    parser.add_argument('--chunk-size', type=int, default=1000,
                       help='Size of text chunks')
    parser.add_argument('--overlap', type=int, default=200,
                       help='Overlap between chunks')
    parser.add_argument('--query', type=str,
                       help='Search query')
    parser.add_argument('--n-results', type=int, default=5,
                       help='Number of results to return')
    parser.add_argument('--stats', action='store_true',
                       help='Show index statistics')

    args = parser.parse_args()

    # Initialize RAG system
    rag = HansardRAG(
        data_dir=args.data_dir,
        index_dir=args.index_dir,
        embedding_model=args.embedding_model
    )

    # Build index
    if args.build_index:
        rag.build_index(chunk_size=args.chunk_size, overlap=args.overlap)

    # Show stats
    if args.stats:
        rag.get_stats()

    # Search
    if args.query:
        results = rag.search(args.query, n_results=args.n_results)

        print(f"\nFound {len(results)} results:\n")
        for i, result in enumerate(results, 1):
            print(f"{'='*60}")
            print(f"Result {i}")
            print(f"Source: {result['metadata']['source']}")
            print(f"{'='*60}")
            print(result['text'][:500] + "..." if len(result['text']) > 500 else result['text'])
            print()

        # Optionally generate answer with LLM
        print("\nGenerating answer with LLM...")
        answer = rag.query_with_llm(args.query, n_results=args.n_results)
        print(f"\nAnswer:\n{answer}")


if __name__ == '__main__':
    main()
