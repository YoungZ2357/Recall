"""
Minimal SFT fine-tuning script for Qwen2.5-1.5B-Instruct.
Usage: python sft_hello_world.py
"""

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

# === Paths (adjust to your setup) ===
MODEL_PATH = "qwen-1.5b"
DATA_PATH = "rq-rag/train.jsonl"
OUTPUT_DIR = "./output/sft-hello-world"

# === Load model & tokenizer ===
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    dtype=torch.bfloat16,
    device_map="auto",
)

# === Load dataset ===
dataset = load_dataset("json", data_files=DATA_PATH, split="train")

# Sanity check
print(f"Dataset size: {len(dataset)}")
print(f"Sample keys: {list(dataset[0].keys())}")
print(f"First message roles: {[m['role'] for m in dataset[0]['messages']]}")

# === LoRA config ===
peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    task_type="CAUSAL_LM",
)

# === Training config ===
training_args = SFTConfig(
    output_dir=OUTPUT_DIR,
    # Training
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    # Memory
    bf16=True,
    gradient_checkpointing=True,
    # Logging
    logging_steps=10,
    save_strategy="epoch",
    # SFT-specific: use chat template from tokenizer
    max_length=2048,
)

# === Trainer ===
trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    processing_class=tokenizer,
    peft_config=peft_config,
)

# === Train ===
trainer.train()

# === Save LoRA weights ===
trainer.save_model(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"LoRA weights saved to {OUTPUT_DIR}")