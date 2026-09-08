# Локальная работа с новым SAS-проектом

Этот документ описывает актуальное подключение нового проекта к SASLite.
Конфигурация проекта, weak-схема, автоматический strict по metadata,
schema-only датасеты, перенос происхождения через `WORK` и dummy fixture CSV
уже реализованы.

## Что устанавливается один раз

SASLite не нужно копировать внутрь каждого проекта:

```bash
cd /path/to/SASLite
python3 -m venv .venv
.venv/bin/pip install -e .
```

Профиль совместимости можно переиспользовать между проектами с одинаковыми
bootstrap-макросами и корпоративными соглашениями. Проектные пути и `LIBNAME`
хранятся в локальном `localsetup.sas`.

## Создание структуры проекта

Из checkout SASLite выполните:

```bash
./scripts/create-saslite-project.py /path/to/new-project
```

Скрипт создаёт:

```text
new-project/
├── saslite-project.json
├── fixtures/
│   ├── ADAM/
│   ├── ADAMP/
│   ├── RAW/
│   └── SDTM/
└── _local/
    ├── config/
    │   ├── localsetup.sas
    │   └── metadata/
    │       └── README.txt
    ├── data/
    │   ├── adam/
    │   ├── raw/
    │   └── sdtm/
    ├── output/
    │   ├── qcosi/
    │   └── osip/
    └── work/
```

По умолчанию `localsetup.sas` содержит примерные библиотеки `ADAM`,
`ADAMP`, `RAW`, `SDTM`, `QCOSI` и `OSIP`. Это только удобный стартовый шаблон:
пользователь может удалить ненужные или добавить свои библиотеки.

Другой набор можно создать сразу:

```bash
./scripts/create-saslite-project.py /path/to/new-project \
  --input-lib SDTM=sdtm \
  --input-lib ADAM=adam \
  --output-lib QC=qc
```

Существующие `saslite-project.json` и `localsetup.sas` не перезаписываются.
`--force` разрешает намеренно обновить сгенерированные шаблоны. В `.gitignore`
добавляется `_local/`, потому что там находятся абсолютные локальные пути,
metadata, локальные данные и результаты.

## Конфигурация проекта

Сгенерированный `saslite-project.json` содержит общие настройки проекта:

```json
{
  "version": 1,
  "default_schema": "weak",
  "metadata_dir": "_local/config/metadata",
  "fixtures_dir": "fixtures"
}
```

SASLite сканирует все `*.csv` в `metadata_dir`. Имя файла определяет libref:

- `sdtm.csv` — metadata библиотеки `SDTM`;
- `adam.csv` — metadata библиотеки `ADAM`;
- `rawall.csv` — metadata библиотеки `RAWALL`.

Количество библиотек заранее неизвестно и ничем не ограничено.

CLI автоматически ищет `saslite-project.json` под `--profile-root` или рядом с
запускаемой SAS-программой. Явный путь можно указать так:

```bash
--project-file /path/to/project/saslite-project.json
```

Если metadata-каталог отсутствует, CSV повреждён, версия формата неизвестна или
libref в marker не совпадает с именем файла, запуск завершается ошибкой. SASLite
не должен молча откатываться в weak.

## Weak и strict

### Weak по умолчанию

`WORK` всегда имеет строгую схему и не наследует `default_schema`.
При этом диагностика промежуточных таблиц сохраняет происхождение переменных:
предположения об исходной weak-библиотеке продолжают указывать на неё.

Если metadata для библиотеки нет, используется `default_schema`, обычно
`weak`. При обращении к неизвестной исходной переменной SASLite использует
missing-value semantics, не меняет исходный датасет и выводит итоговый список
предположений.

Weak относится к неизвестным переменным, а не к отсутствующим датасетам:
исходный датасет должен существовать. Если `RAW.FR` отсутствует, `set raw.fr;`
даёт ошибку и в GUI, и в CLI. Для проверки без локальных данных можно описать
датасет в metadata; тогда библиотека станет strict, а датасет будет доступен
как schema-only с нулём строк.

```text
Expected source variables (weak schema):
  ADAM.ADAE.TRTEMFL (DATA STEP)
```

### Metadata автоматически включает strict

Как только в metadata-каталоге появляется корректный `<libref>.csv`, вся эта
библиотека становится strict. Дополнительный переключатель в JSON не нужен.

Manifest является авторитетным descriptor: он задаёт список датасетов,
переменные, типы, длины, formats, informats, labels и порядок колонок.

- Датасет из manifest без локального файла доступен как schema-only с нулём
  строк.
- Если локальный XPT/SAS7BDAT существует, его строки получают полный descriptor
  manifest.
- Колонки manifest, отсутствующие в локальном файле, представлены missing
  values; сам файл не изменяется.
- Датасет, отсутствующий в strict manifest, считается отсутствующим.
- Обращение к переменной, отсутствующей в manifest, даёт schema warning.

Schema policy и имя исходной библиотеки сохраняются через промежуточные
`WORK`-датасеты. Поэтому diagnostic должен указывать `ADAM.ADAE`, а не
`WORK.ADAE`.

## Получение metadata на корпоративном сервере

1. Откройте `scripts/export-library-metadata.sas` в корпоративном SAS.
2. Укажите назначенную библиотеку:

   ```sas
   %let SASLITE_LIBRARY=SDTM;
   ```

3. Запустите программу.
4. В SAS Log найдите блок между `BEGIN SASLITE METADATA` и
   `END SASLITE METADATA`.
5. Скопируйте блок в `_local/config/metadata/sdtm.csv`.
6. Удалите разрывы страниц и заголовки SAS Log из всех metadata-файлов:

   ```bash
   python3 _local/config/metadata/clean-sas-log-metadata.py
   ```

   Перед изменением каждого файла утилита сохраняет исходник рядом как
   `<libref>.csv.bak`.
7. Ничего в `saslite-project.json` менять не нужно: `SDTM` сразу станет strict.
8. Повторите для любого числа библиотек.

Формат файла:

```text
#SASLITE_METADATA;1;SDTM;2026-08-12T09:30:00
"DATASET";"NAME";"TYPE";"LENGTH";"POSITION";"FORMAT";"INFORMAT";"LABEL"
DM;STUDYID;character;20;1;;;Study Identifier
DM;USUBJID;character;40;4;;;Unique Subject Identifier
DM;AGE;numeric;8;8;BEST12.;;Age
```

SASLite также принимает весь скопированный log-блок с BEGIN/END-строками.
Filename и marker должны обозначать одну библиотеку: marker `SDTM` хранится в
`sdtm.csv`.

Manifest не содержит наблюдений, количества строк и физических корпоративных
путей. Однако имена переменных и labels тоже могут быть конфиденциальными,
поэтому сгенерированный `_local/` по умолчанию исключён из Git.

## Локальный setup

Генератор создаёт примерно такой файл:

```sas
/* Local-only setup generated by SASLite. */
%macro localsetup;
  %let execution_areax=DEV;
  %let saslite_data_root=/path/to/new-project/_local/data;
  %let saslite_output_root=/path/to/new-project/_local/output;

  libname work memory;
  libname adam "&saslite_data_root./adam";
  libname adamp "&saslite_data_root./adam";
  libname raw "&saslite_data_root./raw";
  libname sdtm "&saslite_data_root./sdtm";
  libname qcosi "&saslite_output_root./qcosi";
  libname osip "&saslite_output_root./osip";
%mend localsetup;
```

Путь к data-каталогу задаётся один раз макропеременной. Аналогично отдельно
задаётся output root. Число `LIBNAME` в localsetup не ограничивает metadata
scanner; пользователь правит шаблон под проект.

## Запуск программы

Пример запуска через внешний профиль:

```bash
/path/to/SASLite/scripts/run-saslite \
  --quiet \
  --fail-fast \
  --profile-file /path/to/SASLite/.saslite-private/profiles/project_profile.py \
  --profile-root /path/to/new-project \
  /path/to/new-project/program.sas
```

Программу сначала запускают без адаптированной копии и без добавления колонок в
данные. Missing file остаётся ошибкой. Weak-summary является списком ожиданий,
а strict-warning — расхождением кода с manifest. С `--fail-fast` первый warning
останавливает запуск; без этой опции можно собрать полный список diagnostics.

## Dummy-данные

Схема и строки остаются независимыми. Для датасета можно хранить один
постоянный fixture CSV, например `fixtures/SDTM/AE.csv`. Его строки
накладываются на полную metadata-схему, а отсутствующие колонки и пустые
значения становятся SAS missing. CSV использует UTF-8 и разделитель `;`.

```csv
USUBJID;AETERM;AESTDTC;AEENDTC;AESEV;AESER;AEOUT
TEST-001;Headache;2025-12-31;;;;
TEST-002;Nausea;;2026-01-02;SEVERE;Y;RECOVERED/RESOLVED
```

Имена колонок проверяются без учёта регистра по manifest. Неизвестная колонка,
нечисловое значение числовой переменной, дублированный заголовок и строка
длиннее metadata LENGTH завершают чтение ошибкой. Колонки можно опускать:
SASLite добавит их в порядке manifest и заполнит missing.

Заготовку с правильным заголовком можно создать из manifest:

```bash
saslite-fixture SDTM.AE --project-root /path/to/new-project
```

Из checkout без переустановки entry point доступна та же команда:

```bash
./scripts/create-saslite-fixture.py SDTM.AE \
  --project-root /path/to/new-project
```

Команда создаст `fixtures/SDTM/AE.csv` и не перезапишет существующий файл.
Для намеренной замены используется `--force`; явный конфиг выбирается через
`--project-file`.

Порядок выбора строк фиксирован:

1. `fixtures/<LIBREF>/<DATASET>.csv`, если он существует;
2. локальный XPT/SAS7BDAT из назначенной библиотеки;
3. schema-only датасет с нулём строк.

Fixture полностью заменяет физический источник строк, а не объединяется с ним.
Это не позволяет случайно смешать dummy и реальные наблюдения. Descriptor во
всех трёх случаях берётся из metadata manifest.

## Что ещё предстоит реализовать

- единая строгая проверка переменных в ещё не покрытых PROC;
- стартовая сводка использованных локальных источников строк.
