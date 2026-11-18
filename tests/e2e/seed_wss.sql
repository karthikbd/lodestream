-- A WSS 3.0-shaped content database (the tables and columns lodestream's wss_sql source reads).
-- Content columns use the legacy `image` type, as in WSS 3.0 / MOSS 2007.
IF DB_ID('WSS_Content_E2E') IS NOT NULL
BEGIN
    ALTER DATABASE WSS_Content_E2E SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE WSS_Content_E2E;
END
GO
CREATE DATABASE WSS_Content_E2E;
GO
USE WSS_Content_E2E;
GO
CREATE TABLE dbo.AllLists (tp_ID uniqueidentifier NOT NULL PRIMARY KEY, tp_Title nvarchar(255) NOT NULL);
CREATE TABLE dbo.AllDocs (
    Id uniqueidentifier NOT NULL, SiteId uniqueidentifier NOT NULL, DirName nvarchar(256) NOT NULL,
    LeafName nvarchar(128) NOT NULL, Size int NULL, TimeLastModified datetime NOT NULL, UIVersion int NOT NULL,
    ListId uniqueidentifier NULL, DoclibRowId int NULL, Type tinyint NOT NULL, IsCurrentVersion bit NOT NULL,
    CONSTRAINT PK_AllDocs PRIMARY KEY (SiteId, Id));
CREATE TABLE dbo.AllDocStreams (Id uniqueidentifier NOT NULL, SiteId uniqueidentifier NOT NULL, Content image NULL,
    CONSTRAINT PK_AllDocStreams PRIMARY KEY (SiteId, Id));
CREATE TABLE dbo.AllDocVersions (Id uniqueidentifier NOT NULL, SiteId uniqueidentifier NOT NULL, UIVersion int NOT NULL,
    TimeCreated datetime NOT NULL, Size int NULL, Content image NULL,
    CONSTRAINT PK_AllDocVersions PRIMARY KEY (SiteId, Id, UIVersion));
CREATE TABLE dbo.AllUserData (tp_ListId uniqueidentifier NOT NULL, tp_ID int NOT NULL, tp_IsCurrentVersion bit NOT NULL,
    tp_RowOrdinal tinyint NOT NULL, tp_UIVersion int NOT NULL, nvarchar1 nvarchar(255) NULL,
    tp_ContentType nvarchar(255) NULL);
GO
