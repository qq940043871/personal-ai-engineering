#蒸馏模型
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
from peft import LoraConfig, get_peft_model
from transformers.trainer_callback import TrainerCallback
from transformers.modeling_outputs import CausalLMOutputWithPast

# 设置日志级别
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

class DistillationTrainer(Trainer):
    """自定义训练器实现知识蒸馏"""
    def __init__(self, teacher_model=None, distillation_args=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher_model = teacher_model
        self.distillation_args = distillation_args
        
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        # 学生模型的输出
        student_outputs = model(** inputs)
        student_logits = student_outputs.logits
        
        # 教师模型的输出（不计算梯度）
        with torch.no_grad():
            teacher_outputs = self.teacher_model(**inputs)
            teacher_logits = teacher_outputs.logits
        
        # 计算蒸馏损失（KL散度）
        temperature = self.distillation_args.temperature
        alpha = self.distillation_args.alpha
        
        # 计算学生和教师logits之间的KL散度
        student_probs = torch.nn.functional.log_softmax(student_logits / temperature, dim=-1)
        teacher_probs = torch.nn.functional.softmax(teacher_logits / temperature, dim=-1)
        
        distillation_loss = torch.nn.functional.kl_div(
            student_probs, teacher_probs, reduction="batchmean"
        ) * (temperature ** 2)  # 缩放回原始尺度
        
        # 计算学生模型的标准交叉熵损失
        ce_loss = student_outputs.loss
        
        # 加权组合两种损失
        total_loss = alpha * distillation_loss + (1 - alpha) * ce_loss
        
        return (total_loss, student_outputs) if return_outputs else total_loss

class DistillationArguments:
    """蒸馏参数配置"""
    def __init__(self, temperature=2.0, alpha=0.5):
        self.temperature = temperature  # 蒸馏温度
        self.alpha = alpha  # 蒸馏损失权重

def parse_args():
    parser = argparse.ArgumentParser(description="将GPT-2模型蒸馏为更小的模型")
    
    # 教师模型配置
    parser.add_argument("--teacher_model_name", type=str, 
                        default="gpt2-medium",  # 较大的GPT-2变体作为教师
                        help="教师模型名称")
    
    # 学生模型配置
    parser.add_argument("--student_model_name", type=str, 
                        default="gpt2",  # 较小的GPT-2变体作为学生
                        help="学生模型名称")
    parser.add_argument("--use_lora", action="store_true",
                        help="是否对学生模型使用LoRA")
    parser.add_argument("--quantization_bit", type=int, default=None, choices=[4, 8],
                        help="学生模型量化位数")
    
    # 蒸馏配置
    parser.add_argument("--temperature", type=float, default=2.0,
                        help="蒸馏温度")
    parser.add_argument("--alpha", type=float, default=0.5,
                        help="蒸馏损失权重 (0.0-1.0)")
    
    # 数据集配置
    parser.add_argument("--dataset_name", type=str, default="wikitext",
                        help="数据集名称")
    parser.add_argument("--dataset_config", type=str, default="wikitext-2-raw-v1",
                        help="数据集配置")
    parser.add_argument("--max_length", type=int, default=128,
                        help="最大序列长度")
    
    # LoRA配置
    parser.add_argument("--lora_r", type=int, default=4,
                        help="LoRA低秩矩阵的秩")
    parser.add_argument("--lora_alpha", type=int, default=16,
                        help="LoRA缩放因子")
    parser.add_argument("--lora_target_modules", type=str, default="c_attn",
                        help="应用LoRA的目标模块")
    
    # 训练配置
    parser.add_argument("--output_dir", type=str, default="./distilled_model",
                        help="输出目录")
    parser.add_argument("--per_device_train_batch_size", type=int, default=1,
                        help="每个设备的训练批次大小")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=32,
                        help="梯度累积步数")
    parser.add_argument("--learning_rate", type=float, default=5e-5,
                        help="学习率")
    parser.add_argument("--num_train_epochs", type=int, default=3,
                        help="训练轮数")
    parser.add_argument("--max_grad_norm", type=float, default=0.3,
                        help="梯度裁剪范数")
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    # 检查是否有GPU可用
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"运行设备: {device}")
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 加载教师模型（较大的GPT-2变体）
    print(f"加载教师模型: {args.teacher_model_name}")
    teacher_model = AutoModelForCausalLM.from_pretrained(
        args.teacher_model_name,
        low_cpu_mem_usage=True,
        device_map="auto",
    )
    
    # 加载学生模型（较小的GPT-2变体）
    print(f"加载学生模型: {args.student_model_name}")
    
    student_model_kwargs = {
        "low_cpu_mem_usage": True,
        "device_map": "auto",
    }
    
    # 配置量化
    if args.quantization_bit == 4:
        student_model_kwargs["load_in_4bit"] = True
        student_model_kwargs["quantization_config"] = {
            "load_in_4bit": True,
            "bnb_4bit_compute_dtype": torch.float16,
            "bnb_4bit_quant_type": "nf4",
            "bnb_4bit_use_double_quant": True,
        }
    elif args.quantization_bit == 8:
        student_model_kwargs["load_in_8bit"] = True
    
    student_model = AutoModelForCausalLM.from_pretrained(
        args.student_model_name,
        **student_model_kwargs
    )
    
    # 加载分词器（教师和学生使用相同的分词器）
    tokenizer = AutoTokenizer.from_pretrained(args.teacher_model_name)
    
    # 如果tokenizer没有pad_token，设置pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        teacher_model.config.pad_token_id = teacher_model.config.eos_token_id
        student_model.config.pad_token_id = student_model.config.eos_token_id
    
    # 配置学生模型的LoRA（如果启用）
    if args.use_lora:
        print("对学生模型使用LoRA方法...")
        
        # 配置LoRA
        target_modules = args.lora_target_modules.split(",")
        lora_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            target_modules=target_modules,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        
        # 如果使用量化，准备模型
        if args.quantization_bit is not None:
            from peft import prepare_model_for_kbit_training
            student_model = prepare_model_for_kbit_training(student_model)
        
        student_model = get_peft_model(student_model, lora_config)
    
    # 打印模型信息
    print(f"教师模型参数: {sum(p.numel() for p in teacher_model.parameters()):,}")
    print(f"学生模型参数: {sum(p.numel() for p in student_model.parameters()):,}")
    
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
        fp16=(device.type == "cuda"),  # 仅在GPU上使用FP16
        bf16=False,
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
    
    # 配置蒸馏参数
    distillation_args = DistillationArguments(
        temperature=args.temperature,
        alpha=args.alpha,
    )
    
    # 创建蒸馏训练器
    print("初始化蒸馏训练器...")
    trainer = DistillationTrainer(
        model=student_model,
        teacher_model=teacher_model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        data_collator=data_collator,
        distillation_args=distillation_args,
    )
    
    # 开始蒸馏
    print("开始模型蒸馏...")
    trainer.train()
    
    # 保存蒸馏后的模型
    print(f"保存蒸馏后的模型到 {args.output_dir}")
    if args.use_lora:
        # 只保存LoRA权重
        student_model.save_pretrained(args.output_dir)
    else:
        # 保存整个学生模型
        student_model.save_pretrained(args.output_dir)
    
    tokenizer.save_pretrained(args.output_dir)
    
    print("模型蒸馏完成!")
    print(f"蒸馏后的模型已保存到: {args.output_dir}")

if __name__ == "__main__":
    main()