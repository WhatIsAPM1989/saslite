/* Synthetic example for the built-in example compatibility profile. */
%bootstrap(config=example);
%localsetup;

data work.demo_source;
  input id value;
  datalines;
1 10
2 20
;
run;

%copy_for_validation(dsin=work.demo_source, dsout=work.demo_result);
proc print data=work.demo_result;
run;
