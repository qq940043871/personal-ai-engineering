# 预训练新模型
import os
import math
import torch
from datasets import load_dataset
from transformers import (
    GPT2Config,
    GPT2LMHeadModel,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
)
from peft import LoraConfig, get_peft_model

# 设置日志级别
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

def main():
    # 配置超小模型
    print("配置超小模型...")
    config = GPT2Config(
        vocab_size=50257,
        n_positions=256,
        n_ctx=256,
        n_embd=256,
        n_layer=6,
        n_head=4,
        resid_pdrop=0.1,
        embd_pdrop=0.1,
        attn_pdrop=0.1,
        layer_norm_epsilon=1e-5,
        initializer_range=0.02,
        bos_token_id=50256,
        eos_token_id=50256,
    )
    
    model = GPT2LMHeadModel(config)
    print(f"模型总参数: {sum(p.numel() for p in model.parameters()):,}")
    
    # 检查设备
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"运行设备: {device}")
    
    # 应用LoRA进一步减少训练参数
    use_lora = True
    if use_lora:
        print("应用LoRA...")
        lora_config = LoraConfig(
            r=2,
            lora_alpha=8,
            target_modules=["c_attn"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)
        print(f"可训练参数: {model.print_trainable_parameters()}")
    
    # 加载数据
    print("加载数据集...")
    dataset = load_dataset("wikitext", "wikitext-2-raw-v1", download_mode="force_redownload")
    
    # 加载分词器
    print("加载分词器...")
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    
    # 设置填充标记为EOS标记
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = model.config.eos_token_id
    
    # 预处理数据
    print("预处理数据...")
    def tokenize_function(examples):
        return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=256)
    
    tokenized_datasets = dataset.map(tokenize_function, batched=True)
    
    # 配置训练参数
    print("配置训练参数...")
    training_args = TrainingArguments(
        output_dir="./ultra_tiny_model",
        overwrite_output_dir=True,
        num_train_epochs=50,
        per_device_train_batch_size=32,
        gradient_accumulation_steps=4,
        learning_rate=3e-4,
        weight_decay=0.01,
        warmup_steps=500,
        lr_scheduler_type="cosine",
        save_strategy="steps",
        save_steps=5000,
        logging_steps=100,
        fp16=(device.type == "cuda"),  # 仅在GPU上使用FP16
        tf32=False,  # 禁用TF32，因为它需要NVIDIA Ampere或更新的GPU
        dataloader_num_workers=1,
        remove_unused_columns=False,
    )
    
    # 创建训练器
    print("初始化训练器...")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_datasets["train"],
        data_collator=lambda data: {
            "input_ids": torch.stack([f["input_ids"] for f in data]),
            "attention_mask": torch.stack([f["attention_mask"] for f in data]),
            "labels": torch.stack([f["input_ids"] for f in data]),
        },
    )
    
    # 开始预训练
    print("开始预训练...")
    trainer.train()
    
    # 保存模型
    print("保存模型...")
    trainer.save_model("./ultra_tiny_model")
    tokenizer.save_pretrained("./ultra_tiny_model")
    
    # 评估模型
    print("评估模型...")
    eval_results = trainer.evaluate()
    print(f"困惑度: {math.exp(eval_results['eval_loss']):.2f}")

if __name__ == "__main__":
    main()