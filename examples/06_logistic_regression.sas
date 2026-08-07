/* 06. Logistic Regression - PROC LOGISTIC (Phase 4 feature) */

DATA work.patient_data;
    INPUT age treatment $ outcome;
    /* outcome: 0=no response, 1=response */
    DATALINES;
25 A 0
30 A 1
35 B 1
40 A 0
45 B 1
50 A 1
55 B 1
28 A 0
32 B 0
38 A 1
42 B 1
48 A 1
52 B 1
;
RUN;

/* Simple logistic regression */
PROC LOGISTIC DATA=work.patient_data;
    MODEL outcome = age;
RUN;

/* Logistic regression with categorical predictor */
PROC LOGISTIC DATA=work.patient_data;
    CLASS treatment;
    MODEL outcome = age treatment;
RUN;

/* Logistic regression with odds ratios */
PROC LOGISTIC DATA=work.patient_data;
    CLASS treatment;
    MODEL outcome = age treatment;
    ODDSRATIO age;
    ODDSRATIO treatment;
RUN;

/* Predict probabilities */
PROC LOGISTIC DATA=work.patient_data;
    MODEL outcome = age;
    OUTPUT OUT=work.predicted PREDICTED=prob_response;
RUN;

PROC PRINT DATA=work.predicted;
    VAR age outcome prob_response;
RUN;

/* Intercept-only model (baseline) */
PROC LOGISTIC DATA=work.patient_data;
    MODEL outcome = ;
RUN;
