#!/usr/bin/env python3
"""
Tasmania Parliament Hansard LLM Fine-Tuning Script

This script fine-tunes a language model on cleaned Hansard data using
LoRA (Low-Rank Adaptation) for efficient training.

Usage:
    python 4_train_llm.py --data-file ./cleaned_data/training_data/hansard_training.jsonl \
                          --base-model meta-llama/Llama-3-8b \
                          --output-dir ./models/hansard-llm

Requirements:
    - CUDA-capable GPU (8GB+ VRAM recommended)
    - Python packages: transformers, peft, datasets, accelerate, bitsandbytes
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling
)
from peft import (
    LoraConfig,
    get_peft_model,
    prepare_model_for_kbit_training,
    TaskType
)
import wandb


class HansardLLMTrainer:
    def __init__(
        self,
        base_model: str = "meta-llama/Llama-3-8b",
        data_file: str = "./cleaned_data/training_data/hansard_training.jsonl",
        output_dir: str = "./models/hansard-llm",
        max_length: int = 2048,
        use_4bit: bool = True,
    ):
        """
        Initialize the LLM trainer.

        Args:
            base_model: HuggingFace model ID or path
            data_file: Path to training data (JSONL format)
            output_dir: Directory to save trained model
            max_length: Maximum sequence length
            use_4bit: Use 4-bit quantization (reduces VRAM usage)
        """
        self.base_model = base_model
        self.data_file = Path(data_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_length = max_length
        self.use_4bit = use_4bit

        # Check for GPU
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")

        if self.device == "cuda":
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")

    def load_tokenizer_and_model(self):
        """
        Load tokenizer and base model with optional quantization.
        """
        print(f"Loading tokenizer and model: {self.base_model}")

        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.base_model)

        # Add padding token if missing
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Load model with optional 4-bit quantization
        if self.use_4bit and self.device == "cuda":
            from transformers import BitsAndBytesConfig

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16
            )

            self.model = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True
            )

            # Prepare for k-bit training
            self.model = prepare_model_for_kbit_training(self.model)

        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                device_map="auto",
                trust_remote_code=True
            )

        print(f"Model loaded successfully")

    def setup_lora(self, r: int = 16, lora_alpha: int = 32, lora_dropout: float = 0.05):
        """
        Configure LoRA for parameter-efficient fine-tuning.

        Args:
            r: LoRA rank (lower = fewer parameters, faster training)
            lora_alpha: LoRA scaling parameter
            lora_dropout: Dropout rate for LoRA layers
        """
        print("Configuring LoRA...")

        lora_config = LoraConfig(
            r=r,
            lora_alpha=lora_alpha,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],  # Attention modules
            lora_dropout=lora_dropout,
            bias="none",
            task_type=TaskType.CAUSAL_LM
        )

        self.model = get_peft_model(self.model, lora_config)

        # Print trainable parameters
        trainable_params = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        total_params = sum(p.numel() for p in self.model.parameters())

        print(f"Trainable parameters: {trainable_params:,} ({100 * trainable_params / total_params:.2f}%)")
        print(f"Total parameters: {total_params:,}")

    def load_and_prepare_dataset(self):
        """
        Load and tokenize the training dataset.
        """
        print(f"Loading dataset: {self.data_file}")

        # Load JSONL dataset
        dataset = load_dataset('json', data_files=str(self.data_file))

        print(f"Dataset size: {len(dataset['train'])} examples")

        # Tokenization function
        def tokenize_function(examples):
            # Tokenize the 'text' field
            tokenized = self.tokenizer(
                examples['text'],
                truncation=True,
                max_length=self.max_length,
                padding='max_length',
                return_tensors='pt'
            )
            return tokenized

        # Tokenize dataset
        print("Tokenizing dataset...")
        self.tokenized_dataset = dataset['train'].map(
            tokenize_function,
            batched=True,
            remove_columns=dataset['train'].column_names,
            desc="Tokenizing"
        )

        # Split into train/validation
        split_dataset = self.tokenized_dataset.train_test_split(test_size=0.1, seed=42)
        self.train_dataset = split_dataset['train']
        self.eval_dataset = split_dataset['test']

        print(f"Training examples: {len(self.train_dataset)}")
        print(f"Validation examples: {len(self.eval_dataset)}")

    def train(
        self,
        num_epochs: int = 3,
        batch_size: int = 4,
        learning_rate: float = 2e-4,
        gradient_accumulation_steps: int = 4,
        warmup_steps: int = 100,
        save_steps: int = 500,
        logging_steps: int = 50,
        use_wandb: bool = False,
    ):
        """
        Fine-tune the model on Hansard data.

        Args:
            num_epochs: Number of training epochs
            batch_size: Batch size per device
            learning_rate: Learning rate
            gradient_accumulation_steps: Steps to accumulate gradients
            warmup_steps: Number of warmup steps
            save_steps: Save checkpoint every N steps
            logging_steps: Log metrics every N steps
            use_wandb: Enable Weights & Biases logging
        """
        print("Setting up training...")

        # Initialize wandb if requested
        if use_wandb:
            wandb.init(project="hansard-llm", name=f"hansard-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

        # Training arguments
        training_args = TrainingArguments(
            output_dir=str(self.output_dir),
            num_train_epochs=num_epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            learning_rate=learning_rate,
            warmup_steps=warmup_steps,
            logging_steps=logging_steps,
            save_steps=save_steps,
            eval_steps=save_steps,
            evaluation_strategy="steps",
            save_total_limit=3,
            load_best_model_at_end=True,
            report_to="wandb" if use_wandb else "none",
            bf16=True if self.device == "cuda" else False,  # Use bfloat16 on GPU
            gradient_checkpointing=True,  # Reduce memory usage
            optim="paged_adamw_8bit" if self.use_4bit else "adamw_torch",
        )

        # Data collator
        data_collator = DataCollatorForLanguageModeling(
            tokenizer=self.tokenizer,
            mlm=False  # Causal LM, not masked LM
        )

        # Initialize trainer
        trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=self.train_dataset,
            eval_dataset=self.eval_dataset,
            data_collator=data_collator,
        )

        # Train
        print("Starting training...")
        trainer.train()

        # Save final model
        print(f"Saving model to {self.output_dir}")
        trainer.save_model()
        self.tokenizer.save_pretrained(self.output_dir)

        print("Training complete!")

    def test_inference(self, prompt: str):
        """
        Test the trained model with a sample prompt.

        Args:
            prompt: Test prompt
        """
        print(f"\nTesting inference with prompt: '{prompt}'")

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=200,
                temperature=0.7,
                top_p=0.9,
                do_sample=True
            )

        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        print(f"\nGenerated text:\n{generated_text}")


def main():
    parser = argparse.ArgumentParser(description='Fine-tune LLM on Hansard data')
    parser.add_argument('--base-model', type=str, default='meta-llama/Llama-3-8b',
                       help='Base model to fine-tune')
    parser.add_argument('--data-file', type=str, required=True,
                       help='Path to training data (JSONL)')
    parser.add_argument('--output-dir', type=str, default='./models/hansard-llm',
                       help='Output directory for trained model')
    parser.add_argument('--max-length', type=int, default=2048,
                       help='Maximum sequence length')
    parser.add_argument('--epochs', type=int, default=3,
                       help='Number of training epochs')
    parser.add_argument('--batch-size', type=int, default=4,
                       help='Batch size per device')
    parser.add_argument('--learning-rate', type=float, default=2e-4,
                       help='Learning rate')
    parser.add_argument('--lora-r', type=int, default=16,
                       help='LoRA rank')
    parser.add_argument('--use-4bit', action='store_true', default=True,
                       help='Use 4-bit quantization')
    parser.add_argument('--use-wandb', action='store_true',
                       help='Enable Weights & Biases logging')
    parser.add_argument('--test-prompt', type=str,
                       help='Test prompt after training')

    args = parser.parse_args()

    # Initialize trainer
    trainer = HansardLLMTrainer(
        base_model=args.base_model,
        data_file=args.data_file,
        output_dir=args.output_dir,
        max_length=args.max_length,
        use_4bit=args.use_4bit
    )

    # Load model and tokenizer
    trainer.load_tokenizer_and_model()

    # Setup LoRA
    trainer.setup_lora(r=args.lora_r)

    # Load and prepare dataset
    trainer.load_and_prepare_dataset()

    # Train
    trainer.train(
        num_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        use_wandb=args.use_wandb
    )

    # Test inference if prompt provided
    if args.test_prompt:
        trainer.test_inference(args.test_prompt)


if __name__ == '__main__':
    main()
