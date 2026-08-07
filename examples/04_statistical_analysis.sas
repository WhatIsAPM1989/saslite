/* 04. Statistical Analysis - Descriptive Statistics */

DATA work.measurements;
    INPUT subject $ test1 test2 test3 group $;
    DATALINES;
A1 85 90 88 Control
A2 78 82 80 Control
A3 92 95 93 Control
B1 88 91 89 Treatment
B2 95 98 96 Treatment
B3 82 85 83 Treatment
C1 90 92 91 Control
C2 86 88 87 Treatment
;
RUN;

/* Basic descriptive statistics */
PROC MEANS DATA=work.measurements N MEAN STD MIN MAX;
    VAR test1 test2 test3;
RUN;

/* Statistics by group */
PROC MEANS DATA=work.measurements MEAN STD N;
    CLASS group;
    VAR test1 test2 test3;
RUN;

/* Frequency analysis */
PROC FREQ DATA=work.measurements;
    TABLES group;
RUN;

/* Correlation analysis (Phase 3 feature) */
PROC CORR DATA=work.measurements;
    VAR test1 test2 test3;
RUN;

/* T-test for group comparison (Phase 3 feature) */
PROC TTEST DATA=work.measurements;
    CLASS group;
    VAR test1;
RUN;
