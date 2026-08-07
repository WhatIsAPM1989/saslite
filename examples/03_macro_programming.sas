/* 03. Macro Programming - Variables and Functions */

/* Define macro variables */
%LET year = 2024;
%LET threshold = 50000;

DATA work.employees;
    INPUT name $ age salary department $;
    DATALINES;
Alice 30 55000 IT
Bob 25 40000 HR
Carol 35 65000 IT
David 28 45000 HR
Emma 32 58000 Finance
Frank 29 48000 Finance
;
RUN;

/* Use macro variables in code */
DATA work.high_earners;
    SET work.employees;
    IF salary > &threshold;
    year = &year;
RUN;

PROC PRINT DATA=work.high_earners;
RUN;

/* Conditional macro logic */
%MACRO analyze_dept(dept);
    DATA work.temp_dept;
        SET work.employees;
        WHERE department = "&dept";
    RUN;

    PROC PRINT DATA=work.temp_dept;
    RUN;

    PROC MEANS DATA=work.temp_dept MEAN MIN MAX;
        VAR salary;
    RUN;
%MEND analyze_dept;

/* Call macro */
%analyze_dept(IT);
%analyze_dept(HR);

/* Use %SYSFUNC to call DATA step functions (Phase 3 feature) */
%LET today = %SYSFUNC(TODAY());
%LET current_date = %SYSFUNC(PUTN(&today, YYMMDD10.));
%PUT Current date: &current_date;

%LET avg_salary = %SYSFUNC(MEAN(40000, 45000, 50000, 55000));
%PUT Average salary: &avg_salary;
