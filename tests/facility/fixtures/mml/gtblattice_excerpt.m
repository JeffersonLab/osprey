% Excerpt of MML machine/ALS/GTB/gtblattice.m: the element definitions (correctors,
% quadrupoles, bends, markers) and the lattice arrays LTB1, LTB2, verbatim.
% tests/facility/test_element_table.py scans this file when MML is absent and
% checks it against the MML original when MML is present.

START = marker('START', 'IdentityPass');
BPM   = marker('BPM',   'IdentityPass');
TV    = marker('TV',    'IdentityPass');
END   = marker('END',   'IdentityPass');
HCM = corrector('HCM', GUN_HCM_L, [0 0], 'CorrectorPass');
VCM = corrector('VCM', GUN_VCM_L, [0 0], 'CorrectorPass');
HCM = corrector('HCM', LN_HCM_L, [0 0], 'CorrectorPass');
VCM = corrector('VCM', LN_VCM_L, [0 0], 'CorrectorPass');
LNQ11 = quadrupole('Q', LN_Q, 0.781050/Brho, 'StrMPoleSymplectic4RadPass');
LNQ12 = quadrupole('Q', LN_Q,  -1.2635/Brho,   'StrMPoleSymplectic4RadPass');
LNQ13 = quadrupole('Q', LN_Q, 0.781050/Brho, 'StrMPoleSymplectic4RadPass');
HCM = corrector('HCM', LTB_HCM_L, [0 0], 'CorrectorPass');
VCM = corrector('VCM', LTB_VCM_L, [0 0], 'CorrectorPass');
Q11 = quadrupole('Q', L_Q, -2.0*2.44/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q12 = quadrupole('Q', L_Q,  2.0*3.37/7.2/Brho,   'StrMPoleSymplectic4RadPass');
Q13 = quadrupole('Q', L_Q, -2.0*2.44/7.2/Brho, 'StrMPoleSymplectic4RadPass');
BX = rbend('BX', .5, 0, 0, 0, 0, 'BndMPoleSymplectic4RadPass');
BS = rbend('BEND', .515, 40*pi/180, 0, 0, 0, 'BndMPoleSymplectic4RadPass'); % ???
LTB1 = [
    START
    LTB_START_HCM1
    HCM
    LTB_HCM1_VCM1
    VCM
    LTB_VCM1_BX
    BX
    LTB_BX_VCM2
    VCM
    LTB_VCM2_HCM2
    HCM
    LTB_HCM2_Q11
    Q11
    LTB_Q11_Q12
    Q12
    LTB_Q12_Q13
    Q13
    LTB_Q13_BPM1
    BPM
    LTB_BPM1_TV1
    TV
    LTB_TV1_BPM2
    BPM
    LTB_BPM2_BS
    BS
    ]';

HCM = corrector('HCM', LTB_HCM_L, [0 0], 'CorrectorPass');
VCM = corrector('VCM', LTB_VCM_L, [0 0], 'CorrectorPass');
Q2  = quadrupole('Q', L_Q, 2.0*5.47/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q31 = quadrupole('Q', L_Q, 2.0*6.46/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q32 = quadrupole('Q', L_Q, -2.0*5.83/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q41 = quadrupole('Q', L_Q, 2.0*6.51/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q42 = quadrupole('Q', L_Q, -2.0*5.66/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q5  = quadrupole('Q', L_Q, 2.0*4.3/7.2/Brho, 'StrMPoleSymplectic4RadPass');
Q6  = quadrupole('Q', L_Q, -2.0*3.18/7.2/Brho, 'StrMPoleSymplectic4RadPass');
BR1QD1 = quadrupole('BR1QD1', .3, 0/Brho, 'StrMPoleSymplectic4RadPass'); % incoming beam is far enough separated to not see this magnets field
BR1QF2 = quadrupole('BR1QF2', .15, 0.462/Brho, 'StrMPoleSymplectic4RadPass');
B1 = rbend('BEND', .515,  40*pi/180, 18*pi/180, 18*pi/180, 0, 'BndMPoleSymplectic4RadPass');  % B1: bending, L=0.50, T=40.0, T1=18.0, T2=18.0; ???
B2 = rbend('BEND', .503, -20*pi/180,  0,         0,        0, 'BndMPoleSymplectic4RadPass');  % B2: bending, L=0.50, T=-20.0; ???
B3 = rbend('BEND', .354, -10*pi/180, -5*pi/180, -5*pi/180, 0, 'BndMPoleSymplectic4RadPass');  % B3: bending, L=0.35, T=-10.0, T1=-5.0, T2=-5.0;???
BRKI = rbend('BEND', .5,  -4.5*pi/180, -4.5*pi/180, 0, 0, 'BndMPoleSymplectic4RadPass');  % BRKI: bending, L=0.5, T=-3.5, T1=3.5, T2=0.0;
LTB2 = [
    LTB_BS_VCM3
    VCM
    LTB_VCM3_Q2
    Q2
    LTB_Q2_TV3
    TV
    LTB_TV3_BPM4
    BPM
    LTB_BPM4_B1
    B1
    LTB_B1_Q31
    Q31
    LTB_Q31_Q32
    Q32
    LTB_Q32_VCM4
    VCM
    LTB_VCM4_BPM5
    BPM
    LTB_BPM5_B2
    B2
    LTB_B2_Q41
    Q41
    LTB_Q41_TV4
    TV
    LTB_TV4_Q42
    Q42
    LTB_Q42_VCM5
    VCM
    LTB_VCM5_VCM6
    VCM
    LTB_VCM6_BPM6
    BPM
    LTB_BPM6_Q5
    Q5
    LTB_Q5_BPM7
    BPM
    LTB_BPM7_Q6
    Q6
    LTB_Q6_VCM7
    VCM
    LTB_VCM7_B3
    B3                   % B3 is called BRSI in prints
    LTB_B3_TV5
    TV
    LTB_TV5_BR1QD1
    BR1QD1
    LTB_BR1QD1_TV6
    TV
    LTB_TV6_BRKI
    BRKI
    LTB_BRKI_BR1QF2
    BR1QF2
    LTB_BR1QF2_END
    END
    ]';
