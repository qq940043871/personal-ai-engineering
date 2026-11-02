# 微调新模型
import os
import torch
import argparse
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

# 设置日志级别
os.environ["TRANSFORMERS_VERBOSITY"] = "info"

def parse_args():
    parser = argparse.ArgumentParser(description="在AMD CPU上微调GPT-2超小模型")
    
    # 模型配置
    parser.add_argument("--model_name", type=str, 
                        default="openai-community/gpt2",  # 使用GPT-2超小模型
                        help="要微调的模型名称")
    parser.add_argument("--use_lora", action="store_true",
                        help="是否使用LoRA方法")
    parser.add_argument("--quantization_bit", type=int, default=4,
                        help="量化位数，4或8位量化")
    
    # 数据集配置
    parser.add_argument("--dataset_name", type=str, default="wikitext",
                        help="数据集名称")
    parser.add_argument("--dataset_config", type=str, default="wikitext-2-raw-v1",
                        help="数据集配置")
    parser.add_argument("--max_length", type=int, default=64,
                        help="最大序列长度")
    
    # LoRA配置
    parser.add_argument("--lora_r", type=int, default=4,
                        help="LoRA低秩矩阵的秩")
    parser.add_argument("--lora_alpha", type=int, default=16,
                        help="LoRA缩放因子")
    parser.add_argument("--lora_dropout", type=float, default=0.05,
                        help="LoRA dropout率")
    parser.add_argument("--lora_target_modules", type=str, default="c_attn",
                        help="应用LoRA的目标模块，GPT-2使用'c_attn'")
    
    # 训练配置
    parser.add_argument("--output_dir", type=str, default="./finetuned_gpt2",
                        help="输出目录")
    parser.add_argument("--per_device_train_batch_size", type=int, default=1,
                        help="每个设备的训练批次大小")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=64,
                        help="梯度累积步数")
    parser.add_argument("--learning_rate", type=float, default=5e-5,
                        help="学习率")
    parser.add_argument("--num_train_epochs", type=int, default=1,
                        help="训练轮数")
    parser.add_argument("--max_grad_norm", type=float, default=0.3,
                        help="梯度裁剪范数")
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    # 检查量化设置是否需要LoRA
    if args.quantization_bit in (4, 8) and not args.use_lora:
        print("量化模型需要使用LoRA进行微调，自动启用LoRA...")
        args.use_lora = True
    
    # 检查是否有GPU可用
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"运行设备: {device}")
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 加载模型和分词器
    print(f"加载模型: {args.model_name}")
    
    model_kwargs = {
        "low_cpu_mem_usage": True,
        "device_map": "auto",
    }
    
    # 配置量化
    if args.quantization_bit == 4:
        model_kwargs["quantization_config"] = {
            "load_in_4bit": True,
            "bnb_4bit_compute_dtype": torch.float16,
            "bnb_4bit_quant_type": "nf4",
            "bnb_4bit_use_double_quant": True,
        }
    elif args.quantization_bit == 8:
        model_kwargs["load_in_8bit"] = True
    
    # 加载模型
    model = AutoModelForCausalLM.from_pretrained(args.model_name, **model_kwargs)
    
    # 加载分词器
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    
    # 如果tokenizer没有pad_token，设置pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = model.config.eos_token_id
    
    # 配置LoRA
    if args.use_lora:
        print("使用LoRA方法进行参数高效微调...")
        
        # 准备模型进行量化训练
        model = prepare_model_for_kbit_training(model)
        
        # 配置LoRA (GPT-2的注意力模块名为'c_attn')
        target_modules = args.lora_target_modules.split(",")
        lora_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            target_modules=target_modules,
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        
        model = get_peft_model(model, lora_config)
        
        # 打印可训练参数信息 - 仅在使用LoRA时可用
        print(f"可训练参数: {model.print_trainable_parameters()}")
    
    # 加载数据集
    print(f"加载数据集: {args.dataset_name}/{args.dataset_config}")
    dataset = load_dataset(args.dataset_name, args.dataset_config)
    
    # 预处理数据集
    def preprocess_function(examples):
        # 截断和填充序列
        inputs = tokenizer(
            examples["text"],
            truncation=True,
            max_length=args.max_length,
            padding="max_length",
        )
        inputs["labels"] = inputs["input_ids"].copy()
        return inputs
    
    print("预处理数据集...")
    tokenized_dataset = dataset.map(preprocess_function, batched=True)
    
    # 配置训练参数
    print("配置训练参数...")
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        num_train_epochs=args.num_train_epochs,
        weight_decay=0.01,
        fp16=False,  # CPU不支持FP16
        bf16=False,  # CPU不支持BF16
        logging_dir="./logs",
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=1,
        report_to="none",
        max_grad_norm=args.max_grad_norm,
        dataloader_num_workers=0,  # 减少数据加载线程
    )
    
    # 创建数据收集器
    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    
    # 创建训练器
    print("初始化训练器...")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        data_collator=data_collator,
    )
    
    # 开始训练
    print("开始微调模型...")
    trainer.train()
    
    # 保存微调后的模型
    print(f"保存模型到 {args.output_dir}")
    if args.use_lora:
        # 只保存LoRA权重
        model.save_pretrained(args.output_dir)
    else:
        # 保存整个模型
        model.save_pretrained(args.output_dir)
    
    tokenizer.save_pretrained(args.output_dir)
    
    print("微调完成!")
    print(f"模型已保存到: {args.output_dir}")

if __name__ == "__main__":
    main()