# 验证模型
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# 加载基础模型和分词器
base_model = AutoModelForCausalLM.from_pretrained(
    "gpt2",
    load_in_4bit=True,
    device_map="auto",
)
tokenizer = AutoTokenizer.from_pretrained("gpt2")

# 加载微调后的LoRA权重
model = PeftModel.from_pretrained(base_model, "./finetuned_gpt2")

# 生成文本
prompt = "我是中国人"
inputs = tokenizer(prompt, return_tensors="pt").to("cuda")  # 在GPU上运行

# 生成参数
outputs = model.generate(
    **inputs,
    max_length=100,
    temperature=0.7,
    do_sample=True,
)

# 解码并打印
generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(generated_text)