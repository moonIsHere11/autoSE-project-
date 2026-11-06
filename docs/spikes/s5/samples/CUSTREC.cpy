      * CUSTREC - customer input record (copybook, prefix via REPLACING)
       01  :PFX:-REC.
           05  :PFX:-ID            PIC 9(5).
           05  FILLER              PIC X.
           05  :PFX:-NAME          PIC X(20).
           05  FILLER              PIC X.
           05  :PFX:-BALANCE       PIC S9(5)V99
                                   SIGN LEADING SEPARATE.
           05  FILLER              PIC X.
           05  :PFX:-TYPE          PIC X.
               88  :PFX:-RETAIL    VALUE 'R'.
               88  :PFX:-WHOLESALE VALUE 'W'.
