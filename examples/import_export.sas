/* Import/Export example */

/* Create a dataset */
DATA work.test;
    x = 1;
    y = 2;
    z = x + y;
    OUTPUT;
    x = 10;
    y = 20;
    z = x + y;
    OUTPUT;
    x = 100;
    y = 200;
    z = x + y;
    OUTPUT;
RUN;

PROC PRINT DATA=work.test;
RUN;

PROC SORT DATA=work.test;
    BY z;
RUN;

PROC PRINT DATA=work.test;
RUN;
