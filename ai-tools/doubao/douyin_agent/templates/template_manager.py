import os
import json
from pathlib import Path
from typing import Dict, List, Any


class PromptTemplate:
    def __init__(self, template_id: str, name: str, description: str, 
                 content: str, variables: List[str] = None, 
                 category: str = "general"):
        self.id = template_id
        self.name = name
        self.description = description
        self.content = content
        self.variables = variables or []
        self.category = category

    def render(self, **kwargs) -> str:
        """渲染模板"""
        try:
            return self.content.format(**kwargs)
        except KeyError as e:
            print(f"缺少变量: {e}")
            return self.content

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "variables": self.variables,
            "category": self.category
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PromptTemplate':
        """从字典创建"""
        return cls(
            template_id=data["id"],
            name=data["name"],
            description=data["description"],
            content=data["content"],
            variables=data.get("variables", []),
            category=data.get("category", "general")
        )


class TemplateManager:
    def __init__(self, templates_dir: Path = None):
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent / "templates"
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.templates: Dict[str, PromptTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        """加载所有模板"""
        for template_file in self.templates_dir.glob("*.json"):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    template = PromptTemplate.from_dict(data)
                    self.templates[template.id] = template
            except Exception as e:
                print(f"加载模板 {template_file} 失败: {e}")

    def save_template(self, template: PromptTemplate):
        """保存模板"""
        self.templates[template.id] = template
        template_file = self.templates_dir / f"{template.id}.json"
        with open(template_file, 'w', encoding='utf-8') as f:
            json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)

    def get_template(self, template_id: str) -> PromptTemplate:
        """获取模板"""
        return self.templates.get(template_id)

    def list_templates(self, category: str = None) -> List[PromptTemplate]:
        """列出所有模板"""
        templates = list(self.templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return templates

    def list_categories(self) -> List[str]:
        """列出所有分类"""
        categories = set()
        for template in self.templates.values():
            categories.add(template.category)
        return sorted(list(categories))

    def delete_template(self, template_id: str):
        """删除模板"""
        if template_id in self.templates:
            del self.templates[template_id]
            template_file = self.templates_dir / f"{template_id}.json"
            if template_file.exists():
                template_file.unlink()

    def create_template(self, template_id: str, name: str, description: str, 
                       content: str, variables: List[str] = None, 
                       category: str = "general") -> PromptTemplate:
        """创建模板"""
        template = PromptTemplate(
            template_id=template_id,
            name=name,
            description=description,
            content=content,
            variables=variables,
            category=category
        )
        self.save_template(template)
        return template

    def render_template(self, template_id: str, **kwargs) -> str:
        """渲染指定模板"""
        template = self.get_template(template_id)
        if template:
            return template.render(**kwargs)
        else:
            raise ValueError(f"模板 {template_id} 不存在")


def init_default_templates(template_manager: TemplateManager):
    """初始化默认模板"""
    # 视频脚本生成模板
    video_script_template = PromptTemplate(
        template_id="video_script",
        name="视频脚本生成",
        description="生成抖音视频脚本",
        content="""请生成一个精彩的抖音短视频脚本，主题：{topic}

要求：
- 视频时长：{duration}秒
- 适合抖音平台
- 有吸引力的开头
- 清晰的剧情发展
- 令人印象深刻的结尾
- 适合口语化表达

请直接生成脚本内容，不需要额外说明。""",
        variables=["topic", "duration"],
        category="video"
    )

    # 视频画面描述模板
    video_visual_template = PromptTemplate(
        template_id="video_visual",
        name="视频画面描述",
        description="生成视频画面提示词",
        content="""请根据以下内容生成详细的视频画面描述：

脚本内容：{script}

要求：
- 描述要生动具体
- 适合视频生成模型理解
- 包含人物、场景、动作等元素
- 画面风格：{style}

请直接生成画面描述。""",
        variables=["script", "style"],
        category="video"
    )

    # 抖音视频生成模板
    douyin_video_template = PromptTemplate(
        template_id="douyin_video",
        name="抖音视频生成",
        description="完整的抖音视频生成",
        content="""请生成一个高质量的抖音短视频，要求如下：

主题：{topic}
风格：{style}
受众：{audience}

详细要求：
1. 视频时长：{duration}秒
2. 画面比例：9:16（竖屏）
3. 画面流畅，有吸引力
4. 色彩鲜艳，视觉冲击力强
5. 适合抖音平台播放

请生成完整的视频内容。""",
        variables=["topic", "style", "audience", "duration"],
        category="video"
    )

    # 图片生成模板
    image_template = PromptTemplate(
        template_id="image_generation",
        name="图片生成",
        description="生成高质量图片",
        content="""请生成一张高质量的图片，描述：{description}

要求：
- 风格：{style}
- 尺寸：{width}x{height}
- 高清，细节丰富
- 色彩鲜艳，构图优美""",
        variables=["description", "style", "width", "height"],
        category="image"
    )

    # 标题生成模板
    title_template = PromptTemplate(
        template_id="title_generation",
        name="标题生成",
        description="生成吸引人的视频标题",
        content="""请为以下内容生成一个吸引人的抖音标题：

视频主题：{topic}
内容描述：{description}

要求：
- 吸引人眼球
- 适合抖音平台
- 不超过30字
- 可以使用emoji增加吸引力""",
        variables=["topic", "description"],
        category="text"
    )

    # 保存模板
    templates = [video_script_template, video_visual_template, 
                 douyin_video_template, image_template, title_template]

    for template in templates:
        if template.id not in template_manager.templates:
            template_manager.save_template(template)

    print(f"已初始化 {len(templates)} 个默认模板")