CREATE DATABASE IF NOT EXISTS opendental_dev;
USE opendental_dev;

CREATE TABLE IF NOT EXISTS provider (
    ProvNum     INT PRIMARY KEY AUTO_INCREMENT,
    Abbr        VARCHAR(50),
    FName       VARCHAR(50),
    LName       VARCHAR(50),
    IsHygienist TINYINT(1) DEFAULT 0,
    IsHidden    TINYINT(1) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operatory (
    OperatoryNum INT PRIMARY KEY AUTO_INCREMENT,
    OpName       VARCHAR(50),
    Abbrev       VARCHAR(10),
    IsHidden     TINYINT(1) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appointment (
    AptNum       INT PRIMARY KEY AUTO_INCREMENT,
    AptStatus    TINYINT DEFAULT 1,
    AptDateTime  DATETIME,
    Pattern      VARCHAR(40),
    Op           INT,
    ProvNum      INT,
    ProvHyg      INT DEFAULT 0,
    AptType      INT DEFAULT 0,
    ProcDescript VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS schedule (
    ScheduleNum INT PRIMARY KEY AUTO_INCREMENT,
    SchedDate   DATE,
    StartTime   TIME,
    StopTime    TIME,
    SchedType   TINYINT DEFAULT 0,
    ProvNum     INT DEFAULT 0,
    Op          INT DEFAULT 0,
    Note        VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS appointmenttype (
    AptTypeNum   INT PRIMARY KEY AUTO_INCREMENT,
    AppttypeAbbr VARCHAR(50),
    AppttypeName VARCHAR(100)
);

INSERT INTO provider (Abbr, FName, LName, IsHygienist) VALUES
('DR.MK','MK','Pillai',0),
('DR.MARIO','Mario','Rossi',0),
('DR.KIRAN','Kiran','Patel',0),
('PRIYA','Priya','Sharma',1);

INSERT INTO operatory (OpName, Abbrev) VALUES
('Operatory 1','OP1'),('Operatory 2','OP2'),
('Operatory 3','OP3'),('Hygiene 1','HYG1');

INSERT INTO appointmenttype (AppttypeAbbr, AppttypeName) VALUES
('IMPL','Implant'),('SURG','Surgery'),('EXAM','Exam/Consult'),
('ENDO','Endodontics'),('ORTHO','Orthodontics'),
('HYG','Hygiene/Recall'),('RESTO','Restorative');

INSERT INTO appointment (AptStatus, AptDateTime, Pattern, Op, ProvNum, ProvHyg, AptType, ProcDescript) VALUES
(1,'2026-06-01 09:00:00','//XXXXXXXXXX//',1,1,0,1,'Implant'),
(1,'2026-06-01 10:00:00','//XXXX//',2,2,0,3,'Exam/Consult'),
(1,'2026-06-01 09:30:00','//XXXX//',3,3,0,5,'Endodontics'),
(1,'2026-06-01 09:00:00','//XXXX//',4,0,4,6,'Hygiene/Recall'),
(1,'2026-06-01 14:00:00','//XXXX//',1,1,0,3,'Exam/Consult'),
(1,'2026-06-01 14:30:00','//XXXX//',2,2,0,7,'Restorative'),
(1,'2026-06-02 09:00:00','////XXXXXXXXXX/////',1,1,0,2,'Surgery'),
(1,'2026-06-02 09:00:00','//XXXX//',2,3,0,3,'Exam/Consult'),
(1,'2026-06-02 09:30:00','//XXXX//',4,0,4,6,'Hygiene/Recall'),
(1,'2026-06-02 15:00:00','//XXXX//',1,2,0,7,'Restorative'),
(1,'2026-06-03 09:00:00','//XXXX//',1,1,0,3,'Exam/Consult'),
(1,'2026-06-03 10:00:00','//XXXXXXXXXX//',2,2,0,1,'Implant'),
(1,'2026-06-03 14:00:00','//XXXX//',1,3,0,4,'Orthodontics'),
(1,'2026-06-04 09:00:00','//XXXX//',1,1,0,7,'Restorative'),
(1,'2026-06-04 09:00:00','//XXXX//',2,2,0,3,'Exam/Consult'),
(1,'2026-06-04 09:00:00','//XXXX//',4,0,4,6,'Hygiene/Recall'),
(1,'2026-06-05 09:00:00','////XXXXXXXXXX/////',1,1,0,2,'Surgery'),
(1,'2026-06-05 09:30:00','//XXXX//',2,3,0,3,'Exam/Consult'),
(1,'2026-06-06 09:00:00','//XXXX//',1,2,0,7,'Restorative'),
(1,'2026-06-06 10:00:00','//XXXX//',2,3,0,3,'Exam/Consult'),
(5,'2026-06-03 11:00:00','//XXXX//',3,1,0,3,'Exam/Consult');