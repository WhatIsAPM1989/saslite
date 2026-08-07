/* Hello Data Step — minimal SAS example */

DATA work.employees;
    INPUT name $ age salary;
    DATALINES;
Alice 30 50000
Bob 25 40000
Carol 35 60000
David 28 45000
;
RUN;

PROC PRINT DATA=work.employees;
RUN;

DATA work.senior;
    SET work.employees;
    IF age >= 30;
RUN;

PROC PRINT DATA=work.senior;
RUN;
