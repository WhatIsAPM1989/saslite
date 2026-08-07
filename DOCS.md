# SASLite 使用说明文档

> 轻量级本地 SAS 语言解释器 | 基于 Python + Pandas | 版本 0.1.2

---

## 目录

1. [快速开始](#1-快速开始)
2. [Python API](#2-python-api)
3. [DATA Step 语法](#3-data-step-语法)
4. [PROC SQL 语法](#4-proc-sql-语法)
5. [LIBNAME 库引用](#5-libname--库引用)
6. [PROC 过程步](#6-proc-过程步)
7. [宏系统](#7-宏系统)
8. [内置函数参考](#8-内置函数参考)
9. [表达式与运算符](#9-表达式与运算符)
10. [已知限制](#10-已知限制)
11. [未实现的 SAS 功能](#11-未实现的-sas-功能)

---

## 1. 快速开始

### 安装

```bash
pip install saslite
```

如需从本地源码目录开发安装：

```bash
pip install -e ".[excel,gui]"
```

### 基本用法

```python
from saslite import SasInterpreter

sas = SasInterpreter()

# 直接执行 SAS 代码
result = sas.execute('''
DATA employees;
  INPUT name $ salary;
  DATALINES;
  Alice 50000
  Bob 60000
  ;
RUN;

PROC PRINT DATA=employees; RUN;
''')

print(result.success)  # True/False
```

### 从 Python DataFrame 创建数据集

```python
import pandas as pd

df = pd.DataFrame({'id': [1,2,3], 'name': ['A','B','C'], 'salary': [50000,60000,55000]})
sas.create_dataset('employees', df)  # 默认存入 WORK 库

# 然后就可以在 SAS 代码中引用
sas.execute('PROC PRINT DATA=employees; RUN;')
```

### 导入导出 CSV

```python
# Python API 方式
sas.import_csv('data.csv', 'mydata')
sas.export_csv('mydata', 'output.csv')

# 或在 SAS 代码中
sas.execute('''
PROC IMPORT DATAFILE="data.csv" OUT=work.mydata DBMS=CSV; RUN;
PROC EXPORT DATA=work.mydata OUTFILE="output.csv" DBMS=CSV; RUN;
''')
```

### 执行文件

```python
result = sas.execute_file('script.sas')
```

### 网页 GUI

```bash
pip install "saslite[gui]"
saslite-gui
```

启动后在浏览器打开 `http://localhost:5000`。网页内置 demo 覆盖基础 DATA Step、PROC SQL、CASE WHEN、LIKE / BETWEEN / IS NULL、LAG / DIF、PROC MEANS、PROC PRINT BY、LIBNAME、宏系统和综合示例。

如需桌面窗口模式：

```bash
saslite-desktop
```

后端接口：
- `POST /api/execute`：执行 SAS 代码
- `GET /api/datasets`：列出数据集
- `GET /api/libraries`：按库列出数据集
- `GET /api/datasets/<libref>/<name>`：读取数据集内容
- `DELETE /api/datasets/<libref>/<name>`：删除数据集

---

## 2. Python API

### SasInterpreter 类

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(work_dir: str = None)` | 创建解释器实例，可选工作目录 |
| `execute` | `(source: str, source_name: str = "<input>") -> RunSummary` | 执行 SAS 源代码 |
| `execute_file` | `(path: str) -> RunSummary` | 执行 .sas 文件 |
| `create_dataset` | `(name: str, df: DataFrame, libref: str = "WORK")` | 从 pandas DataFrame 创建数据集 |
| `get_dataset` | `(libref: str, name: str) -> DataFrame` | 获取数据集为 pandas DataFrame |
| `import_csv` | `(filepath: str, dataset_name: str, libref: str = "WORK")` | 导入 CSV 文件 |
| `export_csv` | `(dataset_name: str, filepath: str, libref: str = "WORK")` | 导出数据集为 CSV |

### RunSummary 对象

| 属性 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 全部步骤是否成功 |
| `steps` | `list[StepResult]` | 每个步骤的结果 |
| `error` | `str | None` | 错误信息 |
| `total_steps` | `int` | 执行的步骤数 |

### 库引用

- `WORK` 是默认的临时库，数据在解释器实例生命周期内保持
- 支持 `libref.dataset` 语法，如 `WORK.employees`

---

## 3. DATA Step 语法

### 基本结构

```sas
DATA target_dataset;
  /* statements */
RUN;
```

`target_dataset` 可以是：
- 简单名称：`DATA mydata;`（等同于 `WORK.mydata`）
- 限定名称：`DATA work.mydata;`
- `_NULL_`：不创建输出数据集

### 已实现的 DATA Step 语句

#### INPUT + DATALINES — 内联数据输入

```sas
/* 列表模式 — 空格分隔，$ 表示字符变量 */
DATA employees;
  INPUT name $ salary;
  DATALINES;
  Alice 50000
  Bob 60000
  ;
RUN;

/* 多个变量 */
DATA mixed;
  INPUT id name $ dept $ salary;
  DATALINES;
  1 Alice HR 50000
  2 Bob IT 60000
  ;
RUN;

/* 使用 CARDS 关键字（等同于 DATALINES） */
DATA t;
  INPUT x y;
  CARDS;
  10 20
  30 40
  ;
RUN;

/* $ 在末尾（等同于写在变量名前） */
DATA t;
  INPUT id name $;
  DATALINES;
  1 Alice
  2 Bob
  ;
RUN;

/* 单行格式也支持 */
DATA t;
  INPUT x y;
  DATALINES;
  1 2 3 4
  ;
RUN;
/* 结果：x=1,y=2 和 x=3,y=4 两行 */
```

支持的关键字：`DATALINES`、`CARDS`、`LINES4`

限制：
- 仅支持列表模式（空格分隔），不支持列模式（`INPUT x 1-10`）或格式化模式（`INPUT x 8.2`）
- 每个值必须是单个 token（不含空格）

#### SET — 读取数据集

```sas
DATA new;
  SET old;
RUN;

/* 读取多个数据集（纵向拼接） */
DATA combined;
  SET ds1 ds2 ds3;
RUN;

/* 带数据集选项 */
DATA new;
  SET old(KEEP=name salary);
RUN;

DATA new;
  SET old(DROP=id);
RUN;

DATA new;
  SET old(WHERE=(salary > 50000));
RUN;
```

#### MERGE — 合并数据集

```sas
/* 一对一合并（按位置） */
DATA combined;
  MERGE names salaries;
RUN;

/* 按 BY 变量匹配合并 */
DATA merged;
  MERGE names salaries;
  BY id;
RUN;
```

#### 赋值语句

```sas
DATA new;
  SET old;
  double_sal = salary * 2;
  name_upper = UPCASE(name);
  label = CATS(name, ' - ', dept);
RUN;
```

#### IF / THEN / ELSE

```sas
/* 单语句形式 */
DATA new;
  SET old;
  IF salary > 60000 THEN level = 'Senior';
  ELSE level = 'Junior';
RUN;

/* 块形式 */
DATA new;
  SET old;
  IF salary > 60000 THEN DO;
    level = 'Senior';
    bonus = salary * 0.1;
  END;
  ELSE DO;
    level = 'Junior';
    bonus = salary * 0.05;
  END;
RUN;

/* 子集化 IF（无 THEN）— 仅保留满足条件的行 */
DATA high_paid;
  SET old;
  IF salary >= 60000;
RUN;
```

#### DO 循环

```sas
/* 迭代 DO */
DATA loop;
  DO i = 1 TO 10;
    x = i ** 2;
    OUTPUT;
  END;
RUN;

/* 带 BY 步长 */
DATA step;
  DO i = 0 TO 100 BY 10;
    OUTPUT;
  END;
RUN;

/* DO WHILE */
DATA w;
  i = 1;
  DO WHILE (i <= 5);
    x = i;
    OUTPUT;
    i + 1;
  END;
RUN;

/* DO UNTIL */
DATA u;
  i = 1;
  DO UNTIL (i > 5);
    x = i;
    OUTPUT;
    i + 1;
  END;
RUN;

/* 简单 DO 块 */
DATA s;
  DO;
    x = 1;
    y = 2;
  END;
RUN;
```

#### OUTPUT

```sas
/* 显式 OUTPUT — 手动控制输出时机 */
DATA new;
  SET old;
  OUTPUT;  /* 每行输出 */
RUN;

/* 条件输出 */
DATA new;
  SET old;
  IF salary > 50000 THEN OUTPUT;
RUN;
```

> **注意**：如果存在显式 OUTPUT 语句，则关闭隐式输出。这是标准 SAS 行为。

#### DELETE / STOP

```sas
/* DELETE — 删除当前观测，不输出 */
DATA new;
  SET old;
  IF salary < 30000 THEN DELETE;
RUN;

/* STOP — 立即停止 DATA 步 */
DATA new;
  SET old;
  IF _N_ > 100 THEN STOP;
RUN;
```

#### RETAIN

```sas
/* RETAIN — 在迭代间保留变量值 */
DATA cumulative;
  SET sales;
  RETAIN running_total 0;  /* 初始值为 0 */
  running_total = running_total + amount;
RUN;

/* 不带初始值（默认为缺失） */
DATA lagged;
  SET series;
  RETAIN prev_value;
  change = value - prev_value;
  prev_value = value;
RUN;
```

#### WHERE

```sas
/* WHERE — 在迭代前过滤行 */
DATA filtered;
  SET all_data;
  WHERE salary >= 50000;
RUN;
```

#### LAG / DIF — 滞后与差分函数

```sas
/* LAG — 返回前 n 个观测值 */
DATA lagged;
  SET series;
  prev = LAG(value);     /* 前 1 个值 */
  prev2 = LAG2(value);   /* 前 2 个值 */
RUN;

/* DIF — 当前值与前 n 个值之差 */
DATA diffs;
  SET series;
  change = DIF(value);   /* value - LAG(value) */
  change2 = DIF2(value); /* value - LAG2(value) */
RUN;

/* 配合 RETAIN 做累计计算 */
DATA cumulative;
  SET sales;
  RETAIN running_total 0;
  running_total = running_total + amount;
  lag_amount = LAG(amount);
RUN;
```

支持的函数：`LAG` / `LAG2` ~ `LAG9`、`DIF` / `DIF2` ~ `DIF9`

#### _N_ — 自动变量

`_N_` 是 DATA step 自动变量，表示当前迭代次数（从 1 开始）。

```sas
/* 仅处理前 100 行 */
DATA subset;
  SET big_data;
  IF _N_ > 100 THEN STOP;
RUN;

/* 添加行号 */
DATA numbered;
  SET raw;
  row_id = _N_;
RUN;
```

#### KEEP / DROP

```sas
DATA new;
  SET old;
  KEEP name salary;
RUN;

DATA new;
  SET old;
  DROP temp_var scratch;
RUN;
```

#### RENAME

```sas
DATA new;
  SET old;
  RENAME salary = annual_salary name = employee_name;
RUN;
```

#### FORMAT

```sas
DATA new;
  SET old;
  FORMAT salary DOLLAR10. date DATE9. ratio 8.2;
RUN;
```

支持的格式说明符格式：`FORMATNAMEw.d`（如 `DOLLAR10.`、`COMMA12.2`）

#### LABEL

```sas
DATA new;
  SET old;
  LABEL name = 'Employee Name'
        salary = 'Annual Salary';
RUN;
```

#### ARRAY

```sas
/* 定义数组引用已有变量 */
DATA new;
  ARRAY scores[3] math science english;
  SET students;
  avg = MEAN(of scores[*]);
RUN;

/* arr[i] 下标访问（SAS 1-based indexing） */
DATA new;
  ARRAY vals[3] a b c;
  DO i = 1 TO 3;
    vals[i] = i * 10;          /* a=10; b=20; c=30 */
  END;
RUN;
```

#### FIRST. / LAST. — BY 组首尾标记

```sas
/* 配合 BY 语句，自动生成 FIRST.varname / LAST.varname 布尔标记 */
PROC SORT DATA=scores OUT=sorted;
  BY group;
RUN;

DATA result;
  SET sorted;
  BY group;
  is_first = FIRST.group;    /* 该 BY 组第一条为 1（True） */
  is_last  = LAST.group;     /* 该 BY 组最后一条为 1（True） */
RUN;
```

#### SUBSTR 赋值（左值）

```sas
/* SUBSTR(target, start, length) = value — 原地替换字符串片段 */
DATA result;
  x = 'ABCDEFGH';
  SUBSTR(x, 3, 2) = 'XY';     /* 结果: ABXYEFGH */
RUN;
```

#### PUT 语句

```sas
/* PUT — 输出到日志 */
DATA _NULL_;
  x = 42;
  PUT x;                       /* 输出变量值 */
  PUT 'Hello World';           /* 输出字符串字面量 */
RUN;
```

#### CALL SYMPUT — 动态创建宏变量

```sas
/* CALL SYMPUT(name, value) — 在 DATA step 中设置宏变量
   注意：宏变量值在 DATA step 执行完毕后才能用 & 引用 */
DATA _NULL_;
  CALL SYMPUT('threshold', '55000');
RUN;
/* 后续代码可用 &threshold 引用 */
```

#### LENGTH / ATTRIB — 变量属性设置

```sas
/* LENGTH — 设置变量存储长度（字符型需 $ 前缀） */
DATA result;
  LENGTH NAME $ 20 AGE 4;
  NAME = 'Alice';
  AGE = 30;
RUN;

/* ATTRIB — 一次性设置 FORMAT / LABEL / LENGTH 等多个属性 */
DATA result;
  ATTRIB NAME FORMAT=$10. LABEL='Person Name' LENGTH=20;
  NAME = 'Alice';
RUN;
```

#### UPDATE — DATA step 更新

```sas
/* UPDATE — 按 BY key 用 transaction 数据覆盖 master 对应值 */
DATA result;
  UPDATE master transaction;
  BY id;
RUN;
```

### 未实现的 DATA Step 功能

| 功能 | 状态 |
|------|------|
| INPUT 列模式（`x 1-10`）/ 格式化模式（`x 8.2`） | 未实现（仅列表模式） |
| `CALL` 子程序（除 SYMPUTX 等） | 部分实现（SYMPUT 已实现） |
| 双 SET（并行读取） | 部分支持（多 SET 纵向拼接） |
| `INFORMAT` / `FORMAT` 持久化（仅元数据存储） | 格式不应用到数据 |

---

## 4. PROC SQL 语法

### 基本结构

```sas
PROC SQL;
  /* SQL statements */
QUIT;
```

### SELECT

```sas
/* 基本查询 */
PROC SQL;
  SELECT * FROM employees;
QUIT;

/* 选择特定列 */
PROC SQL;
  SELECT name, salary FROM employees;
QUIT;

/* 带别名 */
PROC SQL;
  SELECT name AS employee_name, salary * 1.1 AS new_salary
  FROM employees;
QUIT;

/* DISTINCT */
PROC SQL;
  SELECT DISTINCT dept_id FROM employees;
QUIT;

/* WHERE 过滤 */
PROC SQL;
  SELECT name, salary
  FROM employees
  WHERE salary > 55000 AND dept_id = 10;
QUIT;

/* ORDER BY 排序 */
PROC SQL;
  SELECT * FROM employees
  ORDER BY salary DESC, name ASC;
QUIT;

/* GROUP BY + 聚合 */
PROC SQL;
  SELECT dept_id, COUNT(id) AS cnt, AVG(salary) AS avg_sal
  FROM employees
  GROUP BY dept_id;
QUIT;

/* HAVING 过滤分组 */
PROC SQL;
  SELECT dept_id, COUNT(id) AS cnt
  FROM employees
  GROUP BY dept_id
  HAVING COUNT(id) >= 2;
QUIT;
```

### JOIN

```sas
/* INNER JOIN */
PROC SQL;
  SELECT e.name, d.dept_name
  FROM employees e
  INNER JOIN departments d ON e.dept_id = d.dept_id;
QUIT;

/* LEFT / RIGHT / FULL / CROSS JOIN */
PROC SQL;
  SELECT e.name, d.dept_name
  FROM employees e
  LEFT JOIN departments d ON e.dept_id = d.dept_id;
QUIT;

/* 表别名支持 AS 关键字或裸别名 */
FROM employees AS e   /* 带 AS */
FROM employees e      /* 裸别名 */
```

### 集合操作

```sas
/* UNION（去重） */
PROC SQL;
  SELECT name FROM t1
  UNION
  SELECT name FROM t2;
QUIT;

/* UNION ALL（不去重） */
PROC SQL;
  SELECT name FROM t1
  UNION ALL
  SELECT name FROM t2;
QUIT;

/* INTERSECT（交集） */
PROC SQL;
  SELECT name FROM t1
  INTERSECT
  SELECT name FROM t2;
QUIT;

/* EXCEPT（差集） */
PROC SQL;
  SELECT name FROM t1
  EXCEPT
  SELECT name FROM t2;
QUIT;
```

### CREATE TABLE

```sas
PROC SQL;
  CREATE TABLE high_salary AS
  SELECT * FROM employees
  WHERE salary >= 60000;
QUIT;
```

### INSERT INTO

```sas
/* 插入值 */
PROC SQL;
  INSERT INTO employees VALUES(6, 'Frank', 10, 52000);
QUIT;

/* 指定列名 */
PROC SQL;
  INSERT INTO employees (id, name, dept_id, salary)
  VALUES(7, 'Gina', 30, 48000);
QUIT;

/* 从 SELECT 插入 */
PROC SQL;
  INSERT INTO archive
  SELECT * FROM employees WHERE dept_id = 10;
QUIT;
```

### UPDATE

```sas
PROC SQL;
  UPDATE employees
  SET salary = salary * 1.1
  WHERE dept_id = 10;
QUIT;

/* 多列更新 */
PROC SQL;
  UPDATE employees
  SET salary = 99999, name = 'Updated'
  WHERE id = 1;
QUIT;
```

### DELETE FROM

```sas
PROC SQL;
  DELETE FROM employees
  WHERE salary < 30000;
QUIT;
```

### 聚合函数

在 SELECT + GROUP BY 中支持的聚合函数：

`COUNT`, `SUM`, `MEAN`, `AVG`, `MIN`, `MAX`, `STD`, `MEDIAN`, `N`

```sas
PROC SQL;
  SELECT dept_id,
         COUNT(*) AS n,
         SUM(salary) AS total,
         MEAN(salary) AS avg_sal
  FROM employees
  GROUP BY dept_id;
QUIT;
```

### CASE WHEN 表达式

```sas
PROC SQL;
  SELECT name, salary,
         CASE
           WHEN salary >= 70000 THEN 'High'
           WHEN salary >= 50000 THEN 'Medium'
           ELSE 'Low'
         END AS salary_level
  FROM employees;
QUIT;

/* 带 ELSE */
PROC SQL;
  SELECT name, dept,
         CASE dept
           WHEN 'IT' THEN 'Technology'
           WHEN 'HR' THEN 'Human Resources'
           ELSE 'Other'
         END AS dept_full
  FROM employees;
QUIT;
```

### LIKE / BETWEEN / IS NULL

```sas
/* LIKE — 模式匹配 */
PROC SQL;
  SELECT * FROM employees
  WHERE name LIKE 'A%';       /* 以 A 开头 */
QUIT;

PROC SQL;
  SELECT * FROM employees
  WHERE name NOT LIKE '%e';   /* 不以 e 结尾 */
QUIT;

/* 通配符：% 匹配任意字符序列，_ 匹配单个字符 */
PROC SQL;
  SELECT * FROM employees
  WHERE name LIKE '_o%';      /* 第二个字符是 o */
QUIT;

/* BETWEEN — 范围查询 */
PROC SQL;
  SELECT * FROM employees
  WHERE salary BETWEEN 50000 AND 70000;
QUIT;

PROC SQL;
  SELECT * FROM employees
  WHERE salary NOT BETWEEN 50000 AND 70000;
QUIT;

/* IS NULL / IS NOT NULL — 空值判断 */
PROC SQL;
  SELECT * FROM employees
  WHERE manager IS NULL;
QUIT;

PROC SQL;
  SELECT * FROM employees
  WHERE email IS NOT NULL;
QUIT;
```

### EXISTS / NOT EXISTS — 子查询存在性检查

```sas
/* EXISTS — 检查子查询是否有结果 */
PROC SQL;
  SELECT * FROM employees e
  WHERE EXISTS (SELECT * FROM departments d WHERE d.dept_id = e.dept_id);
QUIT;

/* NOT EXISTS */
PROC SQL;
  SELECT * FROM employees e
  WHERE NOT EXISTS (SELECT * FROM departments d WHERE d.dept_id = e.dept_id);
QUIT;
```

### 未实现的 SQL 功能

| 功能 | 状态 |
|------|------|
| 子查询（FROM 中的子查询） | 语法支持，执行未测试 |
| 窗口函数（ROW_NUMBER, RANK 等） | 未实现 |
| 多表 UPDATE（FROM 子句） | 未实现 |
| ALTER TABLE | 未实现 |
| CREATE VIEW | 未实现 |
| CREATE INDEX | 未实现 |

---

## 5. LIBNAME — 库引用

```sas
/* 分配库路径 */
LIBNAME mylib "C:/data";

/* 使用库引用访问数据集 */
PROC PRINT DATA=mylib.employees; RUN;

PROC SQL;
  CREATE TABLE mylib.output AS
  SELECT * FROM employees
  WHERE salary > 50000;
QUIT;

/* 清除库引用 */
LIBNAME mylib;
```

- `WORK` 是默认临时库，无需手动分配
- 库路径可以是绝对路径或相对路径
- LIBNAME 后指定的目录会自动创建（如不存在）

### FILENAME — 文件引用

```sas
/* 分配文件引用名 */
FILENAME myfile "C:/data/output.csv";

/* 文件引用名存入宏变量 _FILEREF_{name}，可在后续代码中引用 */
/* 注意：FILENAME 的实际文件操作（读写）尚未完全实现 */
```

---

## 6. PROC 过程步

### PROC PRINT

```sas
/* 基本用法 */
PROC PRINT DATA=employees; RUN;

/* 指定变量 */
PROC PRINT DATA=employees;
  VAR name salary dept_id;
RUN;

/* 带 ID 变量 */
PROC PRINT DATA=employees;
  VAR name salary;
  ID id;
RUN;

/* BY 分组显示（需先排序） */
PROC SORT DATA=employees OUT=sorted;
  BY dept;
RUN;
PROC PRINT DATA=sorted;
  VAR name salary;
  BY dept;
RUN;

/* SUM 汇总（按 BY 组求和） */
PROC PRINT DATA=sorted;
  VAR name salary;
  BY dept;
  SUM salary;
RUN;
```

### PROC SORT

```sas
/* 基本排序 */
PROC SORT DATA=employees OUT=sorted;
  BY salary;
RUN;

/* 降序排序 */
PROC SORT DATA=employees OUT=sorted;
  BY descending salary;
RUN;

/* 多字段排序 */
PROC SORT DATA=employees OUT=sorted;
  BY dept_id descending salary;
RUN;

/* 去重 — 按 BY 变量保留第一条 */
PROC SORT DATA=employees OUT=unique_dept NODUPKEY;
  BY dept_id;
RUN;

/* 去重 — 删除完全重复的行 */
PROC SORT DATA=employees OUT=no_dups NODUPRECS;
  BY id;
RUN;

/* 就地排序（覆盖原数据集） */
PROC SORT DATA=employees;
  BY salary;
RUN;
```

### PROC MEANS / SUMMARY

```sas
/* 显示所有数值变量的描述性统计 */
PROC MEANS DATA=employees;
  VAR salary;
RUN;

/* PROC SUMMARY 与 PROC MEANS 等价 */
PROC SUMMARY DATA=employees;
  VAR salary;
RUN;

/* 指定统计量（N MEAN SUM MIN MAX STD MEDIAN） */
PROC MEANS DATA=employees N MEAN SUM;
  VAR salary;
RUN;

/* CLASS 分组统计 */
PROC MEANS DATA=employees;
  VAR salary;
  CLASS dept;
RUN;

/* BY 分组（需先排序） */
PROC SORT DATA=employees OUT=sorted;
  BY dept;
RUN;
PROC MEANS DATA=sorted;
  VAR salary;
  BY dept;
RUN;

/* OUT= 输出结果到数据集 */
PROC MEANS DATA=employees OUT=summary;
  VAR salary;
  CLASS dept;
RUN;
PROC PRINT DATA=summary; RUN;

/* MAXDEC= 控制小数位数 */
PROC MEANS DATA=employees MAXDEC=2 N MEAN STD;
  VAR salary;
  CLASS dept;
RUN;
```

默认输出：count, mean, std, min, 25%, 50%, 75%, max
指定统计量时仅输出所选统计。

### PROC FREQ

```sas
/* 单变量频率表 */
PROC FREQ DATA=employees;
  TABLES dept_id;
RUN;

/* 交叉表 */
PROC FREQ DATA=employees;
  TABLES dept_id * gender;
RUN;
```

交叉表输出示例：
```
status  N  Y  Total
gender
F       1  1      2
M       1  2      3
Total   2  3      5
```

### PROC CONTENTS

```sas
PROC CONTENTS DATA=employees; RUN;
```

输出包括：引擎类型、观测数、变量数、每个变量的名称、类型（numeric/character）、长度。

### PROC IMPORT

```sas
/* 导入 CSV */
PROC IMPORT DATAFILE="path/to/file.csv"
  OUT=work.mydata
  DBMS=CSV;
RUN;

/* 导入 TSV */
PROC IMPORT DATAFILE="path/to/file.tsv"
  OUT=work.mydata
  DBMS=TAB;
RUN;

/* 导入 Excel（需要 openpyxl） */
PROC IMPORT DATAFILE="path/to/file.xlsx"
  OUT=work.mydata
  DBMS=XLSX;
RUN;

/* 控制选项 */
PROC IMPORT DATAFILE="data.csv"
  OUT=work.mydata
  DBMS=CSV
  GETNAMES=NO       /* 第一行不作为列名 */
  DELIMITER="|";    /* 自定义分隔符 */
RUN;
```

**支持的 DBMS 类型**：`CSV`、`DLM`（分隔符）、`TAB`、`XLSX`/`EXCEL`

### PROC EXPORT

```sas
/* 导出 CSV */
PROC EXPORT DATA=employees
  OUTFILE="output.csv"
  DBMS=CSV;
RUN;

/* 导出 TSV */
PROC EXPORT DATA=employees
  OUTFILE="output.tsv"
  DBMS=TAB;
RUN;

/* 自定义分隔符 */
PROC EXPORT DATA=employees
  OUTFILE="output.txt"
  DBMS=DLM
  DELIMITER="|";
RUN;
```

### PROC APPEND

```sas
/* PROC APPEND — 将 DATA= 数据集追加到 BASE= 数据集尾部 */
DATA base;
  INPUT x y;
  DATALINES;
  1 2
  3 4
  ;
RUN;

DATA extra;
  INPUT x y;
  DATALINES;
  5 6
  ;
RUN;

PROC APPEND BASE=base DATA=extra;
RUN;
/* 结果：base 变为 3 行，包含所有记录 */
```

### PROC DATASETS

```sas
/* PROC DATASETS — 管理数据集（删除、重命名、查看） */
PROC DATASETS;
  DELETE olddata1 olddata2;    /* 删除指定数据集 */
QUIT;

/* MODIFY + RENAME */
PROC DATASETS;
  MODIFY mydata RENAME oldvar = newvar;
QUIT;

/* 指定 LIBRARY */
PROC DATASETS LIBRARY=mylib;
  CONTENTS DATA=specific_ds;   /* 查看单个数据集详情 */
QUIT;
```

> **注意**：PROC DATASETS 必须以 `QUIT;` 结束。

### 未实现/部分实现的 PROC

| PROC | 状态 |
|------|------|
| PROC MEANS 的 NOPRINT | 已实现：抑制输出，OUT= 数据集仍正常写入 |
| PROC TABULATE | 未实现 |
| PROC TRANSPOSE | 未实现 |
| PROC REPORT | 未实现 |
| PROC GPLOT / GCHART | 未实现（图形） |
| PROC REG / LOGISTIC | 未实现（统计建模） |
| PROC SQL 的 QUIT 后代码 | 不支持（QUIT 必须是最后一条） |

---

## 7. 宏系统

### %LET — 宏变量赋值

```sas
%LET threshold = 55000;
%LET dataset = employees;
%LET msg = Hello World;

/* 使用 & 引用 */
DATA high;
  SET &dataset;
  IF salary > &threshold;
RUN;
```

### && — 间接引用

```sas
%LET x = name;
%LET col_&x = employee_name;

/* && 先解析为 &，再解析为值 */
%LET result = &&col_&x;
```

### %MACRO / %MEND — 宏定义

```sas
/* 定义无参宏 */
%MACRO create_report;
  PROC PRINT DATA=employees; RUN;
  PROC MEANS DATA=employees; VAR salary; RUN;
%MEND create_report;

/* 调用宏 */
%create_report;
```

```sas
/* 定义带参宏 */
%MACRO filter_data(dsname, col, threshold);
  DATA filtered;
    SET &dsname;
    IF &col >= &threshold;
  RUN;
%MEND;

/* 调用带参宏 */
%filter_data(work.employees, salary, 60000);
```

### %IF / %THEN / %ELSE — 宏条件编译

```sas
%LET env = PROD;

%IF &env = PROD %THEN %DO;
  DATA config;
    debug = 0;
    log_level = 'ERROR';
  RUN;
%END;
%ELSE %DO;
  DATA config;
    debug = 1;
    log_level = 'DEBUG';
  RUN;
%END;
```

支持的比较运算符：`=`、`NE`、`<>`、`>`、`>=`、`<`、`<=`、`GT`、`GE`、`LT`、`LE`

### %PUT — 宏打印

```sas
%LET msg = Hello;
%PUT &msg World;               /* 输出到日志: Hello World */
%PUT NOTE: Processing done.;   /* 输出带前缀的信息 */
```

### %INCLUDE — 文件包含

```sas
/* 包含同目录下的公共程序 */
%INCLUDE "common.sas";

/* 支持单引号和相对路径 */
%INCLUDE 'macros/setup.sas';
```

相对路径按当前正在执行的 SAS 文件所在目录解析；被包含文件中也可以继续
`%INCLUDE` 其他文件。包含文件会在 `DATALINES` 预处理之前展开，因此被包含
文件可以正常包含 DATA step 内联数据。

限制：
- 当前支持本地文件路径，不支持 SAS fileref 形式。
- `%INCLUDE` 路径中的宏变量暂未展开。
- 循环包含会报错，而不是无限递归。

### %DO %TO %BY — 宏循环

```sas
/* 基本循环 */
%DO i = 1 %TO 5;
  %PUT i = &i;
%END;

/* 带 BY 步长 */
%LET s = 0;
%DO i = 1 %TO 10 %BY 2;
  %LET s = %EVAL(&s + &i);
%END;
```

### %EVAL / %SYSEVALF — 宏表达式求值

```sas
/* %EVAL — 整数算术求值 */
%LET x = %EVAL(3 + 4 * 2);     /* x = 11 */

/* 支持 + - * / 和括号 */
%LET result = %EVAL((100 - 20) / 4);
```

### 注释

```sas
/* 块注释 — 可跨行 */
%LET x = 1;  /* 行内注释 */

/* 块注释会被宏预处理器移除 */
/*  嵌套注释支持有限 — 最外层 /* 内层 */ 会提前关闭 */
```

### 未实现的宏功能

| 功能 | 状态 |
|------|------|
| %GOTO / %LABEL | 未实现 |
| %RETURN | 未实现 |
| %SCAN 宏函数 | 未实现（有 DATA step SCAN） |
| %SUBSTR 宏函数 | 未实现（有 DATA step SUBSTR） |
| %SYSFUNC | 未实现 |
| 宏嵌套调用 | 有限支持（不支持递归） |
| 全局/本地宏变量作用域 | 有限实现 |
| 自动宏变量（SYSDATE, SYSTIME, SYSERR 等） | 未实现 |

---

## 8. 内置函数参考

### 字符函数（22 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| `SUBSTR` | `SUBSTR(string, start [, length])` | 提取子串（从 1 开始） |
| `SCAN` | `SCAN(string, n [, delimiters])` | 提取第 n 个单词 |
| `COMPRESS` | `COMPRESS(string [, chars [, modifiers]])` | 移除/保留指定字符。modifiers: K=保留, L=转小写, U=转大写 |
| `UPCASE` | `UPCASE(string)` | 转大写 |
| `LOWCASE` | `LOWCASE(string)` | 转小写 |
| `STRIP` | `STRIP(string)` | 去除首尾空格 |
| `TRIM` | `TRIM(string)` | 去除尾部空格 |
| `LEFT` | `LEFT(string)` | 左对齐 |
| `CAT` | `CAT(s1, s2, ...)` | 连接字符串 |
| `CATS` | `CATS(s1, s2, ...)` | 连接字符串（自动 strip） |
| `CATX` | `CATX(sep, s1, s2, ...)` | 用分隔符连接字符串 |
| `COMPBL` | `COMPBL(string)` | 多个连续空格压缩为一个 |
| `TRANWRD` | `TRANWRD(string, find, replace)` | 替换子串 |
| `INDEX` | `INDEX(string, substring)` | 查找子串位置（未找到返回 0） |
| `FIND` | `FIND(string, substring [, modifiers])` | 查找子串。modifiers: I=忽略大小写 |
| `COUNT` | `COUNT(string, substring)` | 统计子串出现次数 |
| `REPEAT` | `REPEAT(string, n)` | 重复字符串 n 次 |
| `REVERSE` | `REVERSE(string)` | 反转字符串 |
| `LENGTH` | `LENGTH(string)` | 字符串长度（去除尾部空格） |
| `LENGTHC` | `LENGTHC(string)` | 字符串长度（含尾部空格） |
| `MISSING` | `MISSING(var)` | 测试是否缺失（缺失返回 1，否则 0） |
| `COALESCEC` | `COALESCEC(s1, s2, ...)` | 返回第一个非缺失字符串 |

### 数值函数（23 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| `SUM` | `SUM(n1, n2, ...)` | 求和（忽略缺失值） |
| `MEAN` | `MEAN(n1, n2, ...)` | 均值（忽略缺失值） |
| `MIN` | `MIN(n1, n2, ...)` | 最小值 |
| `MAX` | `MAX(n1, n2, ...)` | 最大值 |
| `N` | `N(n1, n2, ...)` | 非缺失值个数 |
| `NMISS` | `NMISS(n1, n2, ...)` | 缺失值个数 |
| `ROUND` | `ROUND(number [, unit])` | 四舍五入到指定精度（默认 1） |
| `INT` | `INT(number)` | 取整（截断小数） |
| `MOD` | `MOD(dividend, divisor)` | 取模 |
| `CEIL` | `CEIL(number)` | 向上取整 |
| `FLOOR` | `FLOOR(number)` | 向下取整 |
| `ABS` | `ABS(number)` | 绝对值 |
| `SQRT` | `SQRT(number)` | 平方根 |
| `LOG` | `LOG(number)` | 自然对数 |
| `LOG10` | `LOG10(number)` | 以 10 为底的对数 |
| `EXP` | `EXP(number)` | e 的 n 次方 |
| `SIN` | `SIN(number)` | 正弦 |
| `COS` | `COS(number)` | 余弦 |
| `TAN` | `TAN(number)` | 正切 |
| `SIGN` | `SIGN(number)` | 符号（-1, 0, 1） |
| `STD` | `STD(n1, n2, ...)` | 标准差（至少 2 个值） |
| `RANGE` | `RANGE(n1, n2, ...)` | 极差（max - min） |
| `MEDIAN` | `MEDIAN(n1, n2, ...)` | 中位数 |

### 日期函数（14 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| `TODAY` | `TODAY()` | 当前日期（SAS 日期值，距 1960-01-01 的天数） |
| `DATE` | `DATE()` | 同 TODAY |
| `DATETIME` | `DATETIME()` | 当前日期时间（距 1960-01-01 的秒数） |
| `MDY` | `MDY(month, day, year)` | 从月、日、年创建日期 |
| `YEAR` | `YEAR(date)` | 提取年份 |
| `MONTH` | `MONTH(date)` | 提取月份（1-12） |
| `DAY` | `DAY(date)` | 提取日（1-31） |
| `WEEKDAY` | `WEEKDAY(date)` | 星期几（1=周日 ... 7=周六） |
| `QTR` | `QTR(date)` | 季度（1-4） |
| `INTNX` | `INTNX(interval, start, increment [, align])` | 按间隔递增日期。interval: DAY/WEEK/MONTH/QTR/YEAR/HOUR/MINUTE/SECOND。align: B=起始, E=结束, M=中间 |
| `INTCK` | `INTCK(interval, start, end)` | 计算两个日期间的间隔数 |
| `DATEPART` | `DATEPART(datetime)` | 提取日期部分 |
| `TIMEPART` | `TIMEPART(datetime)` | 提取时间部分 |
| `DATEDIF` | `DATEDIF(start, end, unit)` | 计算两个日期之间的天/周/月/季/年差。unit: DAY/WEEK/MONTH/QTR/YEAR |

### 转换函数（2 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| `INPUT` | `INPUT(source, informat)` | 将字符串转换为数值/日期。支持：BEST, F, COMMA, DOLLAR, DATE, DATE9, DDMMYY, MMDDYY, YYMMDD, MONYY, DATETIME |
| `PUT` | `PUT(source, format)` | 将数值/日期转换为字符串。支持：width.dec, DATE9, MMDDYY10, YYMMDD10 |

### 条件函数（3 个）

| 函数 | 语法 | 说明 |
|------|------|------|
| `IFC` | `IFC(condition, true_val, false_val [, missing_val])` | 条件返回字符串 |
| `IFN` | `IFN(condition, true_val, false_val [, missing_val])` | 条件返回数值 |
| `COALESCE` | `COALESCE(n1, n2, ...)` | 返回第一个非缺失数值 |

### SQL 聚合函数

在 PROC SQL SELECT + GROUP BY 中可使用的聚合：

`COUNT`、`SUM`、`MEAN`/`AVG`、`MIN`、`MAX`、`STD`、`MEDIAN`、`N`

### 未实现的常用 SAS 函数

| 函数 | 说明 |
|------|------|
| `RANUNIF` / `RANNOR` | 随机数 |
| `PROBNORM` / `PROBT` / `PROBF` | 概率分布 |
| `PUTN` / `INPUTN` | 动态格式/输入 |
| `STRIPE` | 去除所有空格 |
| `TRANSLATE` | 字符替换（逐字符） |
| `RANK` | 返回字符的 ASCII 码 |
| `BYTE` | 返回 ASCII 码对应的字符 |
| `VERIFY` | 返回第一个不在指定集合中的字符位置 |

---

## 9. 表达式与运算符

### 运算符优先级（从低到高）

| 优先级 | 运算符 | 说明 | 示例 |
|--------|--------|------|------|
| 1 | `OR` | 逻辑或 | `x = 1 OR y = 2` |
| 2 | `AND` | 逻辑与 | `x = 1 AND y > 0` |
| 3 | `NOT` | 逻辑非 | `NOT missing(x)` |
| 4 | `=` `NE` `<>` `>` `>=` `<` `<=` `IN` | 比较 | `salary >= 50000` |
| 5 | `\|\|` | 字符串连接 | `first \|\| ' ' \|\| last` |
| 6 | `+` `-` | 加减 | `a + b - c` |
| 7 | `*` `/` | 乘除 | `price * qty` |
| 8 | 单目 `-` `+` | 正负号 | `-x` |

### 比较运算符

| 运算符 | 含义 | 说明 |
|--------|------|------|
| `=` | 等于 | 缺失值：`.` = `.` 为 True |
| `NE` 或 `<>` | 不等于 | |
| `>` | 大于 | |
| `>=` | 大于等于 | |
| `<` | 小于 | |
| `<=` | 小于等于 | |
| `IN` | 在列表中 | `dept_id IN (10, 20, 30)` |
| `LIKE` | 模式匹配 | `%` 匹配任意字符序列，`_` 匹配单个字符 |
| `NOT LIKE` | 模式不匹配 | |
| `BETWEEN` | 范围判断 | `salary BETWEEN 50000 AND 70000` |
| `NOT BETWEEN` | 范围外判断 | |
| `IS NULL` | 是否为空 | `name IS NULL` |
| `IS NOT NULL` | 是否非空 | `name IS NOT NULL` |

### CASE WHEN 表达式

```sas
/* 搜索式 CASE */
CASE WHEN cond1 THEN result1
     WHEN cond2 THEN result2
     ELSE default_result
END

/* 简单式 CASE */
CASE expr WHEN val1 THEN result1
          WHEN val2 THEN result2
          ELSE default_result
END
```

### 字面量

```sas
42          /* 整数 */
3.14        /* 小数 */
'Hello'     /* 字符串（单引号） */
"World"     /* 字符串（双引号） */
NULL        /* 空值 */
```

### 函数调用

```sas
UPCASE(name)              /* 无参或单参 */
SUBSTR(name, 1, 3)        /* 多参 */
CATS(first, ' ', last)    /* 可变参数 */
SUM(a, b, c, d)           /* 可变参数 */
```

---

## 10. 已知限制

1. **性能**：所有运算基于 pandas DataFrame，大数据集（>100 万行）可能较慢
2. **内存**：所有数据集驻留在内存中，不支持磁盘缓存
3. **并发**：不支持多线程或并行执行
4. **精度**：浮点运算使用 IEEE 754 双精度，与 SAS 的精度有微小差异
5. **缺失值**：数值缺失用 `NaN` 表示，字符串缺失用 `""` 表示，`''` 和 `""` 在 DATALINES 中均视为空值。SAS 的 `.`（数值型缺失）映射为 `NaN`。
6. **日期**：日期基于 1960-01-01 的天数（与 SAS 一致），但时区处理不完整
7. **FORMAT/LABEL**：仅存储为元数据，不改变数据的实际显示格式

---

## 11. 未实现的 SAS 功能

以下功能在 SAS 中存在但 SASLite 当前不支持：

### 数据步
- 双 SET 并行读取
- MODIFY 语句
- INPUT 列模式 / 格式化模式
- CALL 子程序（除 SYMPUT 外）

### 过程步
- PROC TABULATE
- PROC TRANSPOSE
- PROC REPORT
- PROC REG / LOGISTIC / GLM（统计建模）
- PROC UNIVARIATE
- PROC GPLOT / GCHART（图形）
- PROC FORMAT（自定义格式）
- PROC COMPARE
- PROC COPY

### 宏
- %INCLUDE
- %GOTO / %LABEL
- %RETURN
- %SYSFUNC
- %SCAN / %SUBSTR 宏函数
- 宏递归
- 自动宏变量（SYSDATE, SYSTIME, SYSERR 等）

### 全局
- OPTIONS 设置（仅解析，不改变行为）
- ODS 输出分发系统
- 数据库连接（ODBC, JDBC）
- PROC HTTP / JSON
- 窗口函数（SQL）

---

> SASLite 的目标是在纯 Python 环境中提供足够完整的 SAS 语法子集，用于数据处理、清洗和转换任务。它不是 SAS 的完整替代品，而是一个兼容层，让熟悉 SAS 语法的用户能够快速上手 Python 数据处理。
