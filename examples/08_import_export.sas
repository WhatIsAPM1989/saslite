/* 08. Data Import and Export */

/* Create sample data */
DATA work.export_demo;
    INPUT name $ age department $ salary;
    DATALINES;
Alice 30 IT 55000
Bob 25 HR 40000
Carol 35 IT 65000
David 28 Finance 48000
Emma 32 Finance 58000
;
RUN;

/* Export to CSV */
PROC EXPORT DATA=work.export_demo
    OUTFILE='C:/temp/employees.csv'
    DBMS=CSV
    REPLACE;
RUN;

/* Import from CSV */
PROC IMPORT DATAFILE='C:/temp/employees.csv'
    OUT=work.imported_data
    DBMS=CSV
    REPLACE;
    GETNAMES=YES;
RUN;

PROC PRINT DATA=work.imported_data;
RUN;

/* Export with DELIMITER option */
PROC EXPORT DATA=work.export_demo
    OUTFILE='C:/temp/employees_pipe.txt'
    DBMS=DLM
    REPLACE;
    DELIMITER='|';
RUN;

/* Note: Create C:/temp directory first if it doesn't exist */
/* Or change the path to a valid location on your system */
