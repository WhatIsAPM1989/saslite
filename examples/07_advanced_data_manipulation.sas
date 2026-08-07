/* 07. Advanced Data Manipulation */

/* Character functions and data cleaning */
DATA work.raw_names;
    INPUT name $ 1-20 city $ 21-35;
    DATALINES;
 Alice Smith      New York
Bob   Jones       Los Angeles
  Carol  Brown    Chicago
;
RUN;

DATA work.clean_names;
    SET work.raw_names;
    /* Clean up whitespace */
    clean_name = STRIP(name);
    clean_city = STRIP(city);

    /* Extract first and last names */
    first_name = SCAN(clean_name, 1, ' ');
    last_name = SCAN(clean_name, 2, ' ');

    /* Convert to uppercase */
    city_upper = UPCASE(clean_city);

    /* Create concatenated field */
    full_info = CATX(' - ', clean_name, city_upper);

    /* Find substring */
    has_a = INDEX(clean_name, 'a') > 0;

    DROP name city;
RUN;

PROC PRINT DATA=work.clean_names;
RUN;

/* Date and time functions */
DATA work.dates;
    /* Create various date values */
    today = TODAY();
    now = DATETIME();

    /* Date from string */
    date1 = INPUT('01JAN2024', DATE9.);
    date2 = INPUT('2024-06-12', YYMMDD10.);

    /* Date arithmetic */
    next_week = TODAY() + 7;
    next_month = INTNX('MONTH', TODAY(), 1);

    /* Extract date parts */
    current_year = YEAR(TODAY());
    current_month = MONTH(TODAY());
    current_day = DAY(TODAY());

    /* Format for display */
    FORMAT today date1 date2 next_week next_month DATE9.
           now DATETIME20.;
RUN;

PROC PRINT DATA=work.dates;
RUN;

/* Array processing */
DATA work.array_example;
    INPUT id score1 score2 score3 score4;
    ARRAY scores[4] score1 score2 score3 score4;

    /* Calculate statistics using array */
    total = SUM(OF scores[*]);
    average = MEAN(OF scores[*]);
    max_score = MAX(OF scores[*]);

    /* Transform each element */
    DO i = 1 TO 4;
        scores[i] = scores[i] * 1.1;  /* 10% bonus */
    END;

    DROP i;
    DATALINES;
1 85 90 88 92
2 78 82 80 85
3 92 95 93 90
;
RUN;

PROC PRINT DATA=work.array_example;
RUN;
