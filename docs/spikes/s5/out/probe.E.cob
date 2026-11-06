#line 1 "probe.cbl"

 identification division.
 program-id. probe.
 data division.
 working-storage section.
 01 a-num pic 9(3)v9 value 12.5.
 01 b-num pic s9(4) comp-5 value -7.
 01 c-txt pic x(12) value "a  b"";c,d. ".
 01 d-txt pic x(4) value x'41424344'.
 01 e-pic pic 9.
 01 f-pic pic x(5).
 01 g-pic pic $$$,$$9.99-.
 01 h-tab pic 99 value 42.
 01 i-hv pic x(3) value high-values.
 01 j-id-is-long pic 9 value zero.

 procedure division.
 p-main.
 move 1 to a-num e-pic move 'xy' to f-pic
 add 1 2 to a-num
 display c-txt ' *> not a comment ' d-txt
 display 'line  with   spaces' 

 compute b-num = (a-num + 1) * -2 ** 2
 display j-id-is-long g-pic h-tab i-hv
 if a-num >= 1 and e-pic not = 0 display "ok" end-if
 move all 'ab' to f-pic.
 display f-pic
 goback.
