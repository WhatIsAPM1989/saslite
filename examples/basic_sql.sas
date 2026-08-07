/* Basic PROC SQL example */

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

PROC SQL;
    SELECT region, SUM(amount) AS total_sales, COUNT(*) AS n_sales
    FROM work.sales
    GROUP BY region
    ORDER BY total_sales DESC;
QUIT;

PROC SQL;
    CREATE TABLE work.summary AS
    SELECT product, AVG(amount) AS avg_amount, MAX(amount) AS max_amount
    FROM work.sales
    GROUP BY product;
QUIT;

PROC PRINT DATA=work.summary;
RUN;
