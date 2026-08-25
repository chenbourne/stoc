# Level 2 + Level 1+2 processed 下载

范围：样本表中 **Level 2 全部**，以及 **Level 1+2 里的 processed（矩阵 / gef / h5ad / Seurat）**。  
**不下** FASTQ、BAM、SRA、`_RAW.tar`。

按 **数据集去重** 下载，不要按样本行循环。

## 规模（由 `build_manifest.py` 现算）

见 `manifest.tsv` 表头统计；量级约为：

| 批次 | 仓库 | 去重大约 | 方式 |
|------|------|----------|------|
| A | ArrayExpress (`AE`) | 6 | 脚本自动（Processed 文件） |
| B | STOmics (`STDS`) | ~21 | 登录后从数据集页下 gef/h5ad |
| C | Single Cell Portal (`SCP`) | ~19 个 study | 登录 Broad 后从研究页下 |
| D | CNP | ~47，其中已挂 STDS 的可跳过 | 登录 CNGBdb，只要矩阵 |
| E | GEO (`GSE`) | ~199 | 脚本拉 suppl，后缀过滤 |

不在首次批次：CRA / HRA / PRJNA（多为一级测序）。  
**OMIX**：元信息里有 11 个；其中 **6 个 Open-access 可 HTTPS 直链**（见 `omix_direct.tsv`），用 `download_omix.py`；其余需申请/受控。

## 目录约定

```
down/
  README.md              本说明
  build_manifest.py      从 enrich_all.json 生成清单
  download_ae.py         批次 A
  download_geo.py        批次 E
  download_login.py      批次 B/C/D：写出需登录 URL 列表
  manifest.tsv           去重清单（运行 build 后生成）
  login_urls.tsv         STDS/SCP/CNP 待登录下载
  data/                  实际文件（gitignore）
    AE/{accession}/
    STDS/{accession}/
    SCP/{accession}/
    CNP/{accession}/
    GSE/{accession}/
  log/
```

## 怎么下（按顺序）

在 `down` 目录下（仓库里已带好 `manifest.tsv` / `login_urls.tsv`）：

```bash
cd down   # 或 /data2/stoc/down 等你的实际路径
# 一般不用再跑 build_manifest.py；清单已在仓库里
python3 download_ae.py             # 批次 A，体积小、可全自动
python3 download_geo.py --limit 3  # 批次 E 先试跑
python3 download_geo.py            # 批次 E 全量
python3 download_login.py          # 打印 B/C/D 清单，不自动拉登录墙文件
python3 download_omix.py           # OMIX 开放获取（6 个，HTTPS）
```

若要**重新生成**清单，需要本机有 `enrich_all.json`（未推到 GitHub，约数 MB）：

```bash
# 把 enrich_all.json 放到 down/ 同级，或指定路径：
python3 build_manifest.py --json /path/to/enrich_all.json
# 或：STOC_ENRICH_JSON=/path/to/enrich_all.json python3 build_manifest.py
```

GEO 试跑 3 个：

```bash
python3 download_geo.py --limit 3
```

只下某个 GSE：

```bash
python3 download_geo.py --acc GSE123456
```

### 批次 A — ArrayExpress

- 接口：`https://www.ebi.ac.uk/biostudies/api/v1/studies/{E-MTAB-xxx}/files`
- 只保存 Processed / `.tar.gz` / `.h5ad` / `.h5` / matrix 类
- 跳过 FASTQ、BAM、SDRF/IDF

### 批次 B — STOmics

打开 `login_urls.tsv` 中 `kind=STDS` 的页面：

`https://db.cngb.org/stomics/datasets/{STDS…}`

登录 CNGBdb 后下载 **gef / h5ad**，放到 `data/STDS/{accession}/`。  
按数据集下，不要按 STSP 样本再下一遍。

### 批次 C — SCP

`https://singlecell.broadinstitute.org/single_cell/study/{SCP…}`

登录 Broad 后下载 h5ad / Seurat。同一 SCP 被多篇文献引用只下一次。

### 批次 D — CNP

`https://db.cngb.org/data_resources/project/{CNP…}/`

`skip_reason=linked_STDS_already_in_batch_B` 的行：**不要重复下**（矩阵已在对应 STDS）。  
其余只要表达矩阵，不要 raw FASTQ。

### 批次 E — GEO

脚本访问：

`https://ftp.ncbi.nlm.nih.gov/geo/series/GSE{block}nnn/{GSE}/suppl/`

**默认：suppl 里有什么下什么**（含 `.txt.gz` / `.xlsx` / `.tar.gz` / `_RAW.tar` 等），已存在文件会跳过。

```bash
python3 download_geo.py --missing-only   # 只补还没有文件的 GSE（推荐）
python3 download_geo.py                  # 全量（已有文件 resume）
python3 download_geo.py --skip-raw       # 全要但跳过 RAW.tar/fastq/bam
python3 download_geo.py --processed-only # 旧规则：只要 h5/mtx/rds…
```

注意：`_RAW.tar` 可能非常大；磁盘不够再用 `--skip-raw`。  
失败写入 `log/geo_fail.tsv`（部分坏 accession 会 404）。

## 校验

每个 accession 目录里至少有一个非空 processed 文件。  
`log/*_ok.tsv` / `*_fail.tsv` / `*_need_login.tsv` 看进度。

## 注意

- 磁盘：GEO 若误下 RAW.tar 会到 TB；坚持后缀过滤。
- 登录墙：SCP / STDS / 部分 CNP 不能无 cookie 直链；清单里已给出页面。
- Level 1+2 只取 processed，脚本已按文件名过滤 FASTQ/BAM。
