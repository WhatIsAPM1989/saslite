/*
 * Export one corporate SAS library descriptor for SASLite dummy-data mode.
 *
 * Run this program in the corporate SAS environment, not in SASLite.
 * Change only SASLITE_LIBRARY below. The program prints a semicolon-separated
 * metadata block directly to the SAS log. Copy the block into
 * _local/config/metadata/<libref>.csv in the local project. The filename makes
 * that library strict automatically. The block contains one row per variable
 * and no observations, physical paths, or row counts.
 */

%let SASLITE_LIBRARY=SDTM;


%macro saslite_export_library_metadata(libref=);
  %local _saslite_libref
         _saslite_libref_rc
         _saslite_member_count
         _saslite_variable_count
         _saslite_generated_at;

  %if %superq(libref) = %then %do;
    %put ERROR: SASLite metadata export: LIBREF is required.;
    %return;
  %end;

  %let _saslite_libref=%upcase(&libref.);
  %let _saslite_libref_rc=%sysfunc(libref(&_saslite_libref.));

  %if &_saslite_libref_rc. ne 0 %then %do;
    %put ERROR: SASLite metadata export: library &_saslite_libref. is not assigned.;
    %return;
  %end;

  proc sql noprint;
    select count(*)
      into :_saslite_member_count trimmed
      from dictionary.tables
      where libname = "&_saslite_libref."
        and memtype in ('DATA', 'VIEW');
  quit;

  %if &_saslite_member_count. = 0 %then %do;
    %put ERROR: SASLite metadata export: library &_saslite_libref. has no DATA or VIEW members.;
    %return;
  %end;

  proc sql noprint;
    create table work._saslite_variables as
    select memname as DATASET length=32,
           name as NAME length=32,
           case
             when lowcase(type) = 'char' then 'character'
             else 'numeric'
           end as TYPE length=9,
           length as LENGTH,
           varnum as POSITION,
           coalescec(format, '') as FORMAT length=49,
           coalescec(informat, '') as INFORMAT length=49,
           coalescec(label, '') as LABEL length=256
      from dictionary.columns
      where libname = "&_saslite_libref."
      order by memname, varnum;

    select count(*)
      into :_saslite_variable_count trimmed
      from work._saslite_variables;
  quit;

  %let _saslite_generated_at=%sysfunc(datetime(), e8601dt19.);

  data _null_;
    set work._saslite_variables end=_saslite_eof;
    file log dsd dlm=';' linesize=32767 pagesize=32767;
    if _n_ = 1 then do;
      put "----- BEGIN SASLITE METADATA: &_saslite_libref. -----";
      put "#SASLITE_METADATA;1;&_saslite_libref.;&_saslite_generated_at.";
      put '"DATASET";"NAME";"TYPE";"LENGTH";"POSITION";"FORMAT";"INFORMAT";"LABEL"';
    end;
    put DATASET NAME TYPE LENGTH POSITION FORMAT INFORMAT LABEL;
    if _saslite_eof then
      put "----- END SASLITE METADATA: &_saslite_libref. -----";
  run;

  proc datasets library=work nolist;
    delete _saslite_variables;
  quit;

  %put NOTE: SASLite metadata export: printed &_saslite_member_count. members and &_saslite_variable_count. variables from &_saslite_libref. to the SAS log.;
%mend saslite_export_library_metadata;


%saslite_export_library_metadata(
  libref=&SASLITE_LIBRARY.
);
