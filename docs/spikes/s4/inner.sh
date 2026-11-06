#!/usr/bin/env bash
# Executed inside the container (cwd /w = docs/spikes/s4). Each experiment writes
# out/<name>.out / out/<name>.err and appends "name rc wall_s" to out/summary.tsv.
set -u
mkdir -p out

X() {  # X <name> <cmd...>
  local name="$1"; shift
  local t0 t1 rc dt
  t0=$(date +%s.%N)
  "$@" >"out/$name.out" 2>"out/$name.err"; rc=$?
  t1=$(date +%s.%N)
  dt=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.2f", b-a}')
  echo "=== $name  rc=$rc  wall=${dt}s"
  echo "\$ $*"
  sed 's/^/  | /' "out/$name.out" | head -20
  if [ -s "out/$name.err" ]; then echo "  stderr:"; sed 's/^/  ! /' "out/$name.err" | tail -8; fi
  printf '%s\t%s\t%s\n' "$name" "$rc" "$dt" >> out/summary.tsv
}

D="crosshair diffbehavior"
R=cobol_ref
L=llm_variants
H=harness_dom
S=state_toys
M=misc_toys
C=contracts_toys

for g in "$@"; do
case "$g" in
q1)  # plain diffbehavior, default options
  X q1_add_ok            $D $R.ref_add_trunc $L.add_ok
  X q1_add_pymod         $D $R.ref_add_trunc $L.add_bug_pymod
  X q1_add_abs           $D $R.ref_add_trunc $L.add_bug_abs
  X q1_add_notrunc       $D $R.ref_add_trunc $L.add_bug_notrunc
  X q1_round_ok          $D $R.ref_round_drop2 $L.round_ok
  X q1_round_decimal     $D $R.ref_round_drop2 $L.round_ok_decimal
  X q1_round_trunc       $D $R.ref_round_drop2 $L.round_bug_trunc
  X q1_round_banker      $D $R.ref_round_drop2 $L.round_bug_banker
  X q1_round_banker_int  $D $R.ref_round_drop2 $L.round_bug_banker_int
  X q1_round_floor       $D $R.ref_round_drop2 $L.round_bug_floor
  ;;
q2)  # domain restriction
  X q2_nodom_in_domain   $D $R.ref_add_trunc $L.add_ok_in_domain
  X q2_guard_in_domain   $D $H.guard_ref_add $H.guard_llm_add_in_domain
  X q2_guard_notrunc     $D $H.guard_ref_add $H.guard_llm_add_notrunc
  X q2_ign_in_domain     $D $H.ign_ref_add $H.ign_llm_add_in_domain
  X q2_ign_notrunc       $D $H.ign_ref_add $H.ign_llm_add_notrunc
  X q2_ann_in_domain     $D $H.ann_ref_add $H.ann_llm_add_in_domain
  X q2_icr_in_domain     $D $H.icr_ref_add $H.icr_llm_add_in_domain
  X q2_nodom_round_dec   $D $R.ref_round_drop2 $L.round_ok_decimal --per_condition_timeout 30
  X q2_guard_round_dec   $D $H.guard_ref_round $H.guard_llm_round_decimal --per_condition_timeout 30
  X q2_eq_asserts_ok     crosshair check --analysis_kind=asserts $H.eq_asserts_add_in_domain
  X q2_eq_asserts_bug    crosshair check --analysis_kind=asserts $H.eq_asserts_add_notrunc
  X q2_eq_icontract_ok   crosshair check --analysis_kind=icontract $H.eq_icontract_add_in_domain
  X q2_eq_icontract_bug  crosshair check --analysis_kind=icontract $H.eq_icontract_add_notrunc
  ;;
q3)  # mutated state
  X q3_dc_ok             $D $S.ref_para $S.llm_para_ok
  X q3_dc_bug_count      $D $S.ref_para $S.llm_para_bug_count
  X q3_dc_bug_flag       $D $S.ref_para $S.llm_para_bug_flag
  X q3_plain_bug_count   $D $S.ref_para_plain $S.llm_para_plain_bug_count
  X q3_h_ok              $D $S.h_ref $S.h_llm_ok
  X q3_h_bug_count       $D $S.h_ref $S.h_llm_bug_count
  X q3_h_bug_flag        $D $S.h_ref $S.h_llm_bug_flag
  ;;
q3b)  # state harness: budgets and variants
  X q3b_h_bug_count_mui50   $D $S.h_ref $S.h_llm_bug_count --max_uninteresting_iterations 50
  X q3b_h_bug_flag_mui50    $D $S.h_ref $S.h_llm_bug_flag --max_uninteresting_iterations 50
  X q3b_h_bug_count_pct20   $D $S.h_ref $S.h_llm_bug_count --per_condition_timeout 20
  X q3b_h_bug_flag_pct20    $D $S.h_ref $S.h_llm_bug_flag --per_condition_timeout 20
  X q3b_h_ok_pct20          $D $S.h_ref $S.h_llm_ok --per_condition_timeout 20
  X q3b_hi_bug_count        $D $S.hi_ref $S.hi_llm_bug_count
  X q3b_hi_bug_flag         $D $S.hi_ref $S.hi_llm_bug_flag
  X q3b_hi_ok               $D $S.hi_ref $S.hi_llm_ok
  X q3b_hi_ok_pct20         $D $S.hi_ref $S.hi_llm_ok --per_condition_timeout 20
  X q3b_eq_bug_count        crosshair check --analysis_kind=asserts $S.eq_state_bug_count
  X q3b_eq_bug_flag         crosshair check --analysis_kind=asserts $S.eq_state_bug_flag
  X q3b_eq_ok               crosshair check --analysis_kind=asserts $S.eq_state_ok
  ;;
q4)  # options, exceptions, determinism
  X q4_exc_default_msg   $D $M.ref_div $M.llm_div_msg
  X q4_exc_type_msg      $D $M.ref_div $M.llm_div_msg --exception_equivalence TYPE_AND_MESSAGE
  X q4_exc_same_type_msg $D $M.ref_div $M.llm_div_msg --exception_equivalence SAME_TYPE
  X q4_exc_same_type_typ $D $M.ref_div $M.llm_div_type --exception_equivalence SAME_TYPE
  X q4_exc_all_typ       $D $M.ref_div $M.llm_div_type --exception_equivalence ALL
  X q4_mui50_add_ok      $D $R.ref_add_trunc $L.add_ok --max_uninteresting_iterations 50
  X q4_pct10_add_ok      $D $R.ref_add_trunc $L.add_ok --per_condition_timeout 10
  X q4_pct10_pp2_add_ok  $D $R.ref_add_trunc $L.add_ok --per_condition_timeout 10 --per_path_timeout 2
  X q4_pct10_banker_int  $D $R.ref_round_drop2 $L.round_bug_banker_int --per_condition_timeout 10
  X q4_slow_pct10        $D $R.ref_add_trunc $M.llm_add_slow --per_condition_timeout 10
  ;;
q4det)  # determinism: same command twice
  for i in 1 2 3; do
    X q4det_banker_$i    $D $R.ref_round_drop2 $L.round_bug_banker
    X q4det_pymod_$i     $D $R.ref_add_trunc $L.add_bug_pymod
    X q4det_hflag_$i     $D $S.h_ref $S.h_llm_bug_flag
    X q4det_hok_$i       $D $S.h_ref $S.h_llm_ok
  done
  ;;
q5)  # error cases / exit codes
  X q5_no_such_fn        $D $R.ref_add_trunc $L.no_such_function
  X q5_no_such_module    $D $R.ref_add_trunc nosuchmodule.f
  X q5_unannotated       $D $R.ref_add_trunc $M.unannotated
  X q5_side_effect       $D $R.ref_add_trunc $M.llm_add_side_effect
  X q5_nondet            $D $R.ref_add_trunc $M.llm_add_nondet
  X q5_sig_mismatch      $D $R.ref_add_trunc $R.ref_round_drop2
  ;;
q6)  # contracts
  X q6_ic_add_ok         crosshair check --analysis_kind=icontract $C.add_ok
  X q6_ic_round_ok       crosshair check --analysis_kind=icontract $C.round_ok
  X q6_ic_add_bug        crosshair check --analysis_kind=icontract $C.add_bug_notrunc
  X q6_ic_round_banker   crosshair check --analysis_kind=icontract $C.round_bug_banker
  X q6_ic_round_raises   crosshair check --analysis_kind=icontract $C.round_bug_raises
  X q6_ic_module_all     crosshair check --analysis_kind=icontract --report_all $C
  X q6_ic_add_bug_verb   crosshair check --analysis_kind=icontract --report_verbose $C.add_bug_notrunc
  X q6_as_ok             crosshair check --analysis_kind=asserts asserts_toys.add_ok
  X q6_as_bug            crosshair check --analysis_kind=asserts asserts_toys.add_bug
  ;;
q7)  # assert-based equivalence harness (crosshair check) vs diffbehavior
  X q7_eq_round_decimal      crosshair check --analysis_kind=asserts eq_harness.eq_round_decimal
  X q7_eq_round_decimal_p30  crosshair check --analysis_kind=asserts --per_condition_timeout 30 eq_harness.eq_round_decimal
  X q7_eq_round_banker       crosshair check --analysis_kind=asserts eq_harness.eq_round_banker
  X q7_eq_round_floor        crosshair check --analysis_kind=asserts eq_harness.eq_round_floor
  X q7_eq_div_msg            crosshair check --analysis_kind=asserts eq_harness.eq_div_msg
  X q7_eq_div_type           crosshair check --analysis_kind=asserts eq_harness.eq_div_type
  X q7_eq_module_all         crosshair check --analysis_kind=asserts --report_all eq_harness
  ;;
q5b)  # more error cases
  X q5b_check_no_such_fn     crosshair check --analysis_kind=asserts eq_harness.no_such_function
  X q5b_check_syntax_err     crosshair check --analysis_kind=asserts llm_syntax_error.broken
  X q5b_diff_syntax_err      $D $R.ref_add_trunc llm_syntax_error.broken
  ;;
q8)  # module-global WORKING-STORAGE with Decimal fields (INTERFACE.md convention)
  X q8_d_ok_pct30            $D globals_harness.d_ref globals_harness.d_llm_ok --per_condition_timeout 30 --exception_equivalence SAME_TYPE
  X q8_d_bug_pct30           $D globals_harness.d_ref globals_harness.d_llm_bug --per_condition_timeout 30 --exception_equivalence SAME_TYPE
  X q8_d_bug_round_pct30     $D globals_harness.d_ref globals_harness.d_llm_bug_round --per_condition_timeout 30 --exception_equivalence SAME_TYPE
  X q8_eq_ok_pct30           crosshair check --analysis_kind=asserts --report_all --per_condition_timeout 30 globals_harness.eq_ok
  X q8_eq_bug_pct30          crosshair check --analysis_kind=asserts --report_all --per_condition_timeout 30 globals_harness.eq_bug
  X q8_eq_bug_round_pct30    crosshair check --analysis_kind=asserts --report_all --per_condition_timeout 30 globals_harness.eq_bug_round
  ;;
q9)  # determinism of budget-bounded (not exhausted) runs
  for i in 1 2; do
    X q9_round_dec_pct10_$i  $D $R.ref_round_drop2 $L.round_ok_decimal --per_condition_timeout 10
    X q9_h_ok_mui50_$i       $D $S.h_ref $S.h_llm_ok --max_uninteresting_iterations 50
    X q9_eq_dec_pct10_$i     crosshair check --analysis_kind=asserts --report_all --per_condition_timeout 10 eq_harness.eq_round_decimal
  done
  ;;
*) echo "unknown group $g" ;;
esac
done
