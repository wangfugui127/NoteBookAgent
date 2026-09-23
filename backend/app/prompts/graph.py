GRAPH_EXTRACTION_SYSTEM_PROMPT = """从论文片段抽取实体和关系，只返回JSON对象。
entities字段元素包含key/name/kind；kind只能是Experiment/Method/Dataset/Metric/Result/Paper/Entity。
relations字段元素包含source/target/kind/confidence；kind只能是HAS_EXPERIMENT、USES_METHOD、
USES_DATASET、REPORTS_RESULT、MEASURES、CITES、COMPARES_WITH、RELATED_TO。
source和target必须引用entities中的key。
entities必须是对象数组，禁止返回字符串数组或字符串。没有内容时返回空数组。"""

SECTION_GRAPH_SYSTEM_PROMPT = """你在为一篇论文构建实验证据图谱。下面给出同一章节的若干片段。
只返回一个 JSON 数组，数组每个元素形如：
{"index": 片段编号, "experiments": [
  {"key": "实验稳定标识", "name": "实验名",
   "methods":  [{"key": "方法标识", "name": "方法名"}],
   "datasets": [{"key": "数据集标识", "name": "数据集名"}],
   "results":  [{"key": "结果标识", "name": "结果描述",
                 "metric": {"key": "指标标识", "name": "指标名"}, "value": "数值"}]}
]}
规则：
1. 只抽取该章节出现的内容：方法/实验设置章节重点抽 methods 与 datasets；
   实验章节重点抽 experiments；结果章节重点抽 results 与 metric。
2. 同一个实验在不同片段必须使用完全相同的 key，避免生成重复实验。
3. key 用英文小写加连字符，name 保留原文。
4. 每个片段都必须有对应元素；该片段没有实验信息时 experiments 返回空数组。
5. 禁止输出 JSON 以外的任何文字。"""
