-- Run on the OD server to see real provider IDs (ProvNum).
-- Use these to set provider_id for Dr Singh, Erica Scott, Jinwei in config/staff.yaml.
-- Usage (server cmd):
--   mysql -u roster_readonly -p opendental < list_providers.sql
-- or paste into MySQL Workbench / HeidiSQL.

SELECT ProvNum, Abbr, FName, LName, IsHygienist
FROM provider
WHERE IsHidden = 0
ORDER BY IsHygienist, LName;
