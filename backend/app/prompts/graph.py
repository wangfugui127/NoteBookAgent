GRAPH_EXTRACTION_SYSTEM_PROMPT = """从论文片段抽取实体和关系，只返回JSON对象。
entities字段元素包含key/name/kind；kind只能是Entity/Method/Dataset/Metric/Paper。
relations字段元素包含source/target/kind/confidence；kind只能是USES_METHOD、USES_DATASET、
MEASURES_METRIC、CITES、COMPARES_WITH、SUPPORTS、CONTRADICTS、RELATED_TO。
source和target必须引用entities中的key。
entities必须是对象数组，禁止返回字符串数组或字符串。没有内容时返回空数组。"""
