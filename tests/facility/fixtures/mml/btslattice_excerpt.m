% Excerpt of MML machine/ALS/BTS/btslattice.m: the element definitions (correctors,
% quadrupoles, bends, markers) and the lattice arrays BTS, verbatim.
% tests/facility/test_element_table.py scans this file when MML is absent and
% checks it against the MML original when MML is present.

START = marker('START', 'IdentityPass');
BPM   = marker('BPM', 'IdentityPass');
HCM = corrector('HCM', Lcm, [0 0], 'CorrectorPass');
VCM = corrector('VCM', Lcm, [0 0], 'CorrectorPass');
QD  = quadrupole('QD', 1.0E-001,-2.3256700, 'StrMPoleSymplectic4RadPass');
SEN = rbend('SEN', .6, -2.0*pi/180, -1.0*pi/180, -1.0*pi/180, 0, 'BndMPoleSymplectic4RadPass');
SEK = rbend('SEK', .9, -10.0*pi/180, -5.0*pi/180, -5.0*pi/180, 0, 'BndMPoleSymplectic4RadPass');
TV1 = marker('TV', 'IdentityPass');
Q1  = quadrupole('Q', .3, 1.3921, 'StrMPoleSymplectic4RadPass');
TV2 = marker('TV', 'IdentityPass');
Q21 = quadrupole('Q', 3.0E-001,-6.1290000E-001, 'StrMPoleSymplectic4RadPass');
Q22 = quadrupole('Q', 3.0E-001,-2.9980000E-001, 'StrMPoleSymplectic4RadPass');
B1  = rbend('BEND', 1.4, 20*pi/180, 10*pi/180, 10*pi/180, 0, 'BndMPoleSymplectic4RadPass');
Q31 = quadrupole('Q', 3.0E-001,-3.9970000E-001, 'StrMPoleSymplectic4RadPass');
Q32 = quadrupole('Q', 3.0E-001, 1.6189000, 'StrMPoleSymplectic4RadPass');
TV3 = marker('TV', 'IdentityPass');
B2  = rbend('BEND', 1.4, 20*pi/180, 10*pi/180, 10*pi/180, 0.0, 'BndMPoleSymplectic4RadPass');
Q4  = quadrupole('Q', 3.0E-001, 2.2984000, 'StrMPoleSymplectic4RadPass');
TV4 = marker('TV', 'IdentityPass');
Q51 = quadrupole('Q', 3.0E-001,-2.9246000, 'StrMPoleSymplectic4RadPass');
Q52 = quadrupole('Q', 3.0E-001, 2.7048000, 'StrMPoleSymplectic4RadPass');
B3  = rbend('BEND', 1.4, 20*pi/180, 10*pi/180, 10*pi/180, 0, 'BndMPoleSymplectic4RadPass');
Q61 = quadrupole('Q', 3.0E-001, 2.1585000, 'StrMPoleSymplectic4RadPass');
Q62 = quadrupole('Q', 3.0E-001,-2.0719000, 'StrMPoleSymplectic4RadPass');
B4  = rbend('BEND', 1.3989, 18.4*pi/180, 9.2*pi/180, 9.2*pi/180, 0.0, 'BndMPoleSymplectic4RadPass');
TV5 = marker('TV', 'IdentityPass');
Q7  = quadrupole('Q', 3.0E-001, 1.7455000, 'StrMPoleSymplectic4RadPass');
TV6 = marker('TV', 'IdentityPass');
SIK = rbend('SIK', 9.0E-1, 10.07*pi/180, 10.07*pi/180, 0.0*pi/180, 0.0, 'BndMPoleSymplectic4RadPass');
SIN = rbend('SIN', .6, 2.0*pi/180, 2.0*pi/180, 0.0*pi/180, 0.0, 'BndMPoleSymplectic4RadPass');
SRBMP3 = rbend('SRBMP3', .7, 0, 0, 0, 0, 'BndMPoleSymplectic4RadPass');
SRBMP4 = rbend('SRBMP4', .7, 0, 0, 0, 0, 'BndMPoleSymplectic4RadPass');
CTR_SRQF = marker('CTR_SRQF', 'IdentityPass');
SRTV1 = marker('TV', 'IdentityPass');
BTS = [START AP L1 SEN L2 SEK L3 HCM L4 BPM L5 VCM L6 TV1 L7 Q1 L8 HCM L9 VCM ...
L10 TV2 L11 Q21 L12 Q22 L13 HCM L14 VCM L15 B1 L16 BPM L17 Q31 L18 Q32 ...
L19 HCM L20 VCM L21 TV3 L22 B2 L23 Q4 L24 TV4 L25 HCM L26 VCM L27 Q51 L28 Q52 ...
L29 BPM L30 B3 L31 HCM L32 VCM L33 BPM L34 Q61 L35 Q62 L36 HCM L37 VCM L38 B4 ...
L39 TV5 L40 BPM L41 Q7 L42 HCM L43 VCM L44 BPM L45 HCM L46 VCM L47 TV6 L48 SIK L49 SIN ...
L50 SRBMP3 L50 SRBMP4 L51 CTR_SRQF SRTV1];
