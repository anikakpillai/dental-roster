DROP DATABASE IF EXISTS opendental_dev;
CREATE DATABASE opendental_dev CHARACTER SET utf8mb4;
USE opendental_dev;

CREATE TABLE provider (
    ProvNum INT PRIMARY KEY, Abbr VARCHAR(50), FName VARCHAR(100),
    LName VARCHAR(100), IsHidden TINYINT DEFAULT 0, IsHygienist TINYINT DEFAULT 0
);
INSERT INTO provider VALUES
(1,'PILLAI','MK','Pillai',0,0),
(2,'MARIO','Mario','Afrashtehfar',0,0),
(4,'HYG1','Hygiene','Provider',0,1);

CREATE TABLE operatory (
    OperatoryNum INT PRIMARY KEY, OpName VARCHAR(100), Abbrev VARCHAR(50),
    ProvDentist INT, ProvHygienist INT, IsHygiene TINYINT DEFAULT 0, IsHidden TINYINT DEFAULT 0
);
INSERT INTO operatory VALUES
(1,'Op 1','OP1',1,0,0,0),(2,'Op 2','OP2',2,0,0,0),
(3,'Op 3','OP3',1,0,0,0),(4,'Hygiene','HYG',0,4,1,0);

CREATE TABLE appointment (
    AptNum INT PRIMARY KEY AUTO_INCREMENT, PatNum INT, AptStatus TINYINT,
    AptDateTime DATETIME, Pattern VARCHAR(255), Op INT, ProvNum INT,
    ProvHyg INT DEFAULT 0, ProcDescript VARCHAR(255)
);
INSERT INTO appointment (PatNum,AptStatus,AptDateTime,Pattern,Op,ProvNum,ProvHyg,ProcDescript) VALUES
(101,1,'2026-06-22 09:00:00','XX//XX//XX//',1,1,0,'Implant Placement'),
(102,1,'2026-06-22 10:00:00','XX//XX//',1,1,0,'Implant Consult'),
(103,1,'2026-06-22 09:30:00','XXXX//',2,2,0,'Crown Prep'),
(104,1,'2026-06-22 11:00:00','XX//XX//',2,2,0,'Restorative'),
(105,1,'2026-06-22 14:00:00','XX//XX//XX//',1,1,0,'Surgery Extraction'),
(106,1,'2026-06-22 15:00:00','XXXX//',2,2,0,'Filling'),
(201,1,'2026-06-23 09:00:00','XX//XX//XX//XX//',1,1,0,'Implant Placement'),
(203,1,'2026-06-23 09:00:00','XXXX//',2,2,0,'Crown Prep'),
(205,1,'2026-06-23 09:00:00','XXXXXX',4,0,4,'Hygiene/Recall'),
(206,1,'2026-06-23 14:00:00','XX//XX//',1,1,0,'Surgery'),
(301,1,'2026-06-24 09:00:00','XXXX//',2,2,0,'Crown Prep'),
(302,1,'2026-06-24 10:00:00','XX//XX//',2,2,0,'Restorative'),
(401,1,'2026-06-25 09:00:00','XX//XX//XX//',1,1,0,'Implant Placement'),
(403,1,'2026-06-25 09:00:00','XXXX//',2,2,0,'Crown Prep'),
(405,1,'2026-06-25 14:00:00','XX//XX//',1,1,0,'Implant Consult'),
(501,1,'2026-06-26 09:00:00','XX//XX//',1,1,0,'Implant Restoration'),
(503,1,'2026-06-26 09:00:00','XXXX//',2,2,0,'Crown Prep'),
(601,1,'2026-06-27 09:00:00','XX//XX//XX//',1,1,0,'Implant Placement'),
(701,5,'2026-06-22 16:00:00','XX//',1,1,0,'Broken Appt'),
(702,3,'2026-06-23 16:00:00','XX//',2,2,0,'Unscheduled');

SELECT 'Providers' AS t, COUNT(*) AS n FROM provider
UNION ALL SELECT 'Operatories', COUNT(*) FROM operatory
UNION ALL SELECT 'Active appts', COUNT(*) FROM appointment WHERE AptStatus IN (1,2)
UNION ALL SELECT 'Excluded appts', COUNT(*) FROM appointment WHERE AptStatus IN (3,5);
