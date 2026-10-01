from siliconflow_llm import SiliconFlowLLM
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

# 初始化SiliconFlow LLM
llm = SiliconFlowLLM(
    api_key="sk-REPLACE_WITH_YOUR_KEY",  # 替换为你的API密钥
    model_id="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",  # 模型ID
    temperature=0.7,
    max_tokens=512
)

# 创建一个简单的Prompt模板
prompt = PromptTemplate(
    input_variables=["question"],
    template="请回答以下问题: {question}"
)

# 创建LLMChain
chain = LLMChain(llm=llm, prompt=prompt)

# 调用模型
result = chain.run("什么是人工智能？请用简单的语言解释。")
print(result)

# 也可以直接调用LLM
direct_result = llm("介绍一下LangChain的主要功能")
print(direct_result)
