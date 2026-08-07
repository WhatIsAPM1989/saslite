/* 02. PROC SQL - Queries, Aggregation, and Joins */

DATA work.sales;
    INPUT region $ product $ amount;
    DATALINES;
East Widget 100
West Gadget 200
East Widget 150
North Gizmo 300
South Gadget 250
East Gizmo 180
West Widget 120
South Widget 90
;
RUN;

/* Basic aggregation and grouping */
PROC SQL;
    SELECT region,
           SUM(amount) AS total_sales,
           COUNT(*) AS n_sales,
           AVG(amount) AS avg_sales
    FROM work.sales
    GROUP BY region
    ORDER BY total_sales DESC;
QUIT;

/* Create summary table */
PROC SQL;
    CREATE TABLE work.product_summary AS
    SELECT product,
           AVG(amount) AS avg_amount,
           MAX(amount) AS max_amount,
           MIN(amount) AS min_amount
    FROM work.sales
    GROUP BY product;
QUIT;

PROC PRINT DATA=work.product_summary;
RUN;

/* Window functions (Phase 3 feature) */
PROC SQL;
    SELECT region, product, amount,
           ROW_NUMBER() OVER (PARTITION BY region ORDER BY amount DESC) AS rank_in_region,
           SUM(amount) OVER (PARTITION BY region) AS regional_total
    FROM work.sales
    ORDER BY region, rank_in_region;
QUIT;
