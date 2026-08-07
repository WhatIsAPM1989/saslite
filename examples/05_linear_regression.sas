/* 05. Linear Regression - PROC REG (Phase 4 feature) */

DATA work.study_data;
    INPUT hours_studied score age;
    DATALINES;
2 65 18
3 70 19
4 75 18
5 80 20
6 85 19
7 90 21
8 92 20
4 72 18
5 78 19
6 82 20
;
RUN;

/* Simple linear regression */
PROC REG DATA=work.study_data;
    MODEL score = hours_studied;
RUN;

/* Multiple linear regression */
PROC REG DATA=work.study_data;
    MODEL score = hours_studied age;
RUN;

/* Regression with residual analysis */
PROC REG DATA=work.study_data;
    MODEL score = hours_studied age;
    OUTPUT OUT=work.reg_output PREDICTED=predicted_score RESIDUAL=residual;
RUN;

PROC PRINT DATA=work.reg_output;
    VAR hours_studied age score predicted_score residual;
RUN;

/* Check for multicollinearity with VIF */
DATA work.multivariate;
    INPUT y x1 x2 x3;
    DATALINES;
10 2 4 6
12 3 5 7
15 4 6 8
18 5 7 9
20 6 8 10
22 7 9 11
25 8 10 12
;
RUN;

PROC REG DATA=work.multivariate;
    MODEL y = x1 x2 x3 / VIF;
RUN;
