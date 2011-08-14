#!/usr/bin/env python
import sys
import os
import csv
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import numpy as np
#import cx_Oracle as ora
import psycopg2 as pg
import sqlalchemy.pool as pool
pg = pool.manage(pg)

from wpp.config import dbsvrs, wpp_tables, sqls, DB_UPLOAD, \
        tbl_field, tbl_forms, tbl_idx, tbl_files


def usage():
    import time
    print """
db.py - Copyleft 2009-%s Yan Xiaotian, xiaotian.yan@gmail.com.
Abstraction layer for WPP radiomap DB handling.

usage:
    db <option> 
option:
    normal:  wpp_clusteridaps & wpp_cfps.
    call  :  All-clustering table import.
    cincr :  Incr-clustering table import.
    uprecs:  uprecs rawdata & version tables import.
example:
    #db.py normal
""" % time.strftime('%Y')


class WppDB(object):
    def __init__(self,dsn=None,tables=wpp_tables,tbl_field=tbl_field,tbl_forms=tbl_forms,sqls=sqls,
            tbl_files=tbl_files,tbl_idx=tbl_idx,dbtype=None):
        if not dsn: sys.exit('Need DSN info!')
        if not dbtype: sys.exit('Need DB type!') 
        self.dbtype = dbtype
        if self.dbtype == 'postgresql':
            try:
                self.con = pg.connect(dsn) 
                self.con.set_isolation_level(pg.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            except Exception, e:
                if not e.pgcode or not e.pgerror: sys.exit('PostgreSQL: Connection failed!\n%s' % e)
                else: sys.exit('\nERROR: %s: %s\n' % (e.pgcode, e.pgerror))
        elif self.dbtype == 'oracle':
            try:
                self.con = ora.connect(dsn) 
            except ora.DatabaseError, e:
                sys.exit('\nERROR: %s' % e)
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)

        if not tbl_field or not tbl_forms or not tables:
            sys.exit('Need name, field, format definition for all tables!')
        self.tables = wpp_tables
        self.tbl_field = tbl_field
        self.tbl_forms = tbl_forms[self.dbtype]
            
        if not sqls: sys.exit('Need sql set!')
        self.sqls = sqls

        self.tbl_files = tbl_files
        self.tbl_idx = tbl_idx

        self.cur = self.con.cursor()

    def close(self):
        self.cur.close()
        self.con.close()

    def execute(self, sql='', fetch_one=True):
        """Raw sql execute api for external module. NOT recommend to be used in db module."""
        self.cur.execute(sql)
        try:
            if fetch_one: result = self.cur.fetchone()
            else: result = self.cur.fetchall()
            return result
        except (pg.ProgrammingError, Exception), e:
            return None

    def _getRowCount(self, table_inst):
        self.cur.execute( self.sqls['SQL_SELECT'] % ('COUNT(*)', table_inst) )
        return self.cur.fetchone()[0]

    def getRawdataVersion(self):
        table_name = 'wpp_uprecsver'
        table_inst = self.tables[table_name]
        if self._getRowCount(table_inst):
            self.cur.execute( self.sqls['SQL_SELECT'] % ('ver_uprecs', table_inst) )
            return self.cur.fetchone()[0]
        else: return None

    def setRawdataVersion(self, ver_new):
        table_name = 'wpp_uprecsver'
        table_inst = self.tables[table_name]
        if self._getRowCount(table_inst):
            sql = self.sqls['SQL_UPDATE'] % (table_inst, 'ver_uprecs', str(ver_new))
        else: sql = self.sqls['SQL_INSERT'] % (table_inst, '', '(%s)'%ver_new)
        self.cur.execute(sql)
        self.con.commit()

    def updateIndexes(self, doflush=False):
        if self.tbl_idx:
            for table_name in self.tables:
                table_inst = self.tables[table_name]
                for col_name in self.tbl_idx[table_name]:
                    if not col_name: continue
                    # Index naming rule: i_tablename_colname.
                    idx_name = 'i_%s_%s' % (table_inst, col_name)
                    # Drop indexs.
                    if doflush: 
                        sql_drop_idx = self.sqls['SQL_DROP_IDX'] % idx_name 
                        self.cur.execute(sql_drop_idx)
                        print sql_drop_idx
                    # Create indexs.
                    sql_make_idx = self.sqls['SQL_CREATEIDX'] % (idx_name,table_inst,col_name)
                    self.cur.execute(sql_make_idx)
                    print sql_make_idx
        else: print 'No Index defined!'

    def initTables(self, doDrop=False):
        for table_name in self.tables:
            table_inst = self.tables[table_name]
            if doDrop:
                self.cur.execute(self.sqls['SQL_DROPTB_IE'] % table_inst)
                self.cur.execute(self.sqls['SQL_CREATETB'] % \
                        (table_inst, self.tbl_forms[table_name]))
                print 'DROP & CREATE TABLE: |%s|' % table_inst
            else:
                print 'TRUNCATE TABLE: %s' % table_inst
                self.cur.execute(self.sqls['SQL_TRUNCTB'] % table_inst)

    def loadTableFiles(self, tbl_files=None):
        for table_name in self.tables:
            table_inst = self.tables[table_name]
            csvfile = self.tbl_files[table_name]
            if not os.path.isfile(csvfile):
                sys.exit('\n%s is NOT a file!' % (csvfile))
            # Load the csv data into WPP tables.
            self._loadFile(csvfile=csvfile, table_name=table_name)
            # Update the number of records.
            print 'Total [%s] rows in |%s|' % (self._getRowCount(table_inst), table_inst)

    def loadClusteredData(self, tbl_files=None):
        if not self.tbl_files: 
            if not tbl_files:
                sys.exit('\nERROR: %s: Need a csv file!\n' % csvfile)
            else: self.tbl_files = tbl_files
        # Create WPP tables.
        self.initTables(doDrop=True)
        # Update indexs.
        self.updateIndexes(doflush=False)
        # Load csv clustered data into DB tables.
        self.loadTableFiles()

    def _loadFile(self, csvfile=None, table_name=None):
        if self.dbtype == 'postgresql':
            if not table_name == 'wpp_uprecsinfo': cols = None
            else: cols = self.tbl_field[table_name]
            table_inst = self.tables[table_name]
            try:
                self.cur.copy_from(file(csvfile), table_inst, sep=',', columns=cols)
            except Exception, e:
                if not e.pgcode or not e.pgerror: sys.exit(e)
                else: sys.exit('\nERROR: %s: %s\n' % (e.pgcode, e.pgerror))
        elif self.dbtype == 'oracle':
            # Import csv data.
            csvdat = csv.reader( open(csvfile,'r') )
            try:
                indat = [ line for line in csvdat ]
            except csv.Error, e:
                sys.exit('\nERROR: %s, line %d: %s!\n' % (csvfile, csvdat.line_num, e))
            self.insertMany(table_name=table_name, indat=indat)
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)

    def _getNewCid(self, table_inst=None):
        self.cur.execute( self.sqls['SQL_SELECT'] % ('max(clusterid)', table_inst) )
        cur_cid = self.cur.fetchone()[0]
        new_cid = cur_cid+1 if cur_cid else 1 # cur_cid=None when the table is empty.
        return new_cid

    def areaname2code(self, areaname_en=None):
        """ Area name(en) from google reverse-geocoding api to code specified by NBSC.
        http://www.stats.gov.cn/tjbz/xzqhdm
        """
        sql = "select code from wpp_area where name_en='%s'" % areaname_en
        self.cur.execute(sql)
        areacode = self.cur.fetchone()
        return areacode

    def areaLocation(self, laccid=None):
        sql = "select areacode,areaname_en,areaname_cn from wpp_cellarea where laccid='%s'" % laccid
        self.cur.execute(sql)
        area = self.cur.fetchone()
        return area

    def laccidLocation(self, laccid=None):
        sql = "select lat,lon,ee from wpp_celloc where laccid='%s'" % laccid
        self.cur.execute(sql)
        laccid_loc = self.cur.fetchone()
        if laccid_loc: laccid_loc = [ float(x) for x in laccid_loc ]
        return laccid_loc

    def addCellLocation(self, laccid=None, loc=[]):
        table_name = 'wpp_celloc'
        lat, lon, h, ee = loc
        indat = [[ laccid, lat, lon, h, ee ]]
        self.insertMany(table_name=table_name, indat=indat)

    def insertMany(self, table_name=None, indat=None, verb=False):
        table_inst = self.tables[table_name]
        if self.dbtype == 'postgresql':
            str_indat = '\n'.join([ ','.join([str(col) for col in fp]) for fp in indat ])
            file_indat = StringIO(str_indat)
            if not table_name == 'wpp_uprecsinfo': cols = None
            else: cols = self.tbl_field[table_name]
            try:
                self.cur.copy_from(file_indat, table_inst, sep=',', columns=cols)
            except Exception, e:
                if not e.pgcode or not e.pgerror: sys.exit(e)
                #else: sys.exit('\nERROR: %s: %s\n' % (e.pgcode, e.pgerror))
                raise Exception(e.pgerror)
            if verb: print 'Add %d rows -> |%s|' % (len(indat), table_inst)
        elif self.dbtype == 'oracle':
            table_field = self.tbl_field[table_name]
            num_fields = len(table_field)
            bindpos = '(%s)' % ','.join( ':%d'%(x+1) for x in xrange(num_fields) )
            self.cur.prepare(self.sqls['SQL_INSERT'] % \
                    (table_inst, '(%s)'%(','.join(table_field)), bindpos))
            self.cur.executemany(None, indat)
            if verb: print 'Add %d rows -> |%s|' % (self.cur.rowcount, table_inst)
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)
        self.con.commit()

    def addCluster(self, macs=None):
        table_name = 'wpp_clusteridaps'
        table_inst = self.tables[table_name]
        new_cid = self._getNewCid(table_inst=table_inst)
        cidmacseq = []
        for seq,mac in enumerate(macs):
            cidmacseq.append([ new_cid, mac, seq+1 ])
        self.insertMany(table_name=table_name, indat=cidmacseq)
        return new_cid

    def addFps(self, cid=None, fps=None):
        table_name = 'wpp_cfps'
        cids = np.array([ [cid] for i in xrange(len(fps)) ])
        fps = np.array(fps)
        cidfps = np.append(cids, fps, axis=1).tolist()
        self.insertMany(table_name=table_name, indat=cidfps)

    def getCIDcntMaxSeq(self, macs=None):
        table_name = 'wpp_clusteridaps'
        table_inst = self.tables[table_name]
        if not type(macs) is list: macs = list(macs)
        num_macs = len(macs)
        if not num_macs: sys.exit('Null macs!')
        strWhere = "%s%s%s" % ("keyaps='", "' or keyaps='".join(macs), "'")
        if self.dbtype == 'postgresql':
            sql1 = self.sqls['SQL_SELECT'] % \
                ("clusterid as cid, COUNT(clusterid) as cidcnt", 
                 "%s where (%s) group by clusterid order by cidcnt desc) a, %s t \
                 where (cid=clusterid and cidcnt=%s) group by cid,cidcnt order by cidcnt desc" % \
                (table_inst, strWhere, table_inst, num_macs))
        elif self.dbtype == 'oracle':
            sql1 = self.sqls['SQL_SELECT'] % \
                ("clusterid cid, COUNT(clusterid) cidcnt", 
                 "%s where (%s) group by clusterid order by cidcnt desc) a, %s t \
                 where (a.cid=t.clusterid and a.cidcnt=%s) group by a.cid,a.cidcnt order by cidcnt desc" % \
                (table_inst, strWhere, table_inst))
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)
        sql = self.sqls['SQL_SELECT'] % ("cid,cidcnt,max(t.seq)", "(%s"%sql1)
        #print sql
        self.cur.execute(sql)
        return self.cur.fetchall()

    #maxNI,keys = [2, [
    #    [['00:21:91:1D:C0:D4', '00:19:E0:E1:76:A4', '00:25:86:4D:B4:C4'],
    #        [[5634, 5634, 39.898019, 116.367113, '-83|-85|-89']] ],
    #    [['00:21:91:1D:C0:D4', '00:25:86:4D:B4:C4'],
    #        [[6161, 6161, 39.898307, 116.367233, '-90|-90']] ] ]]
    def getBestClusters(self, macs=None):
        if not type(macs) is list: macs = list(macs)
        num_macs = len(macs)
        if not num_macs: sys.exit('Null macs!')
        # fetch id(s) of best cluster(s).
        cidcnt = self._getBestCIDMaxNI(macs)
        if not cidcnt.any(): return [0,None]
        maxNI = cidcnt[0,1]
        idx_maxNI = cidcnt[:,1].tolist().count(maxNI)
        best_clusters = cidcnt[:idx_maxNI,0]
        #print best_clusters
        cfps = self._getFPs(cids=best_clusters)
        #print cfps
        aps = self._getKeyMACs(cids=best_clusters)
        #print aps
        cids = aps[:,0].tolist()
        keys = []
        for i,cid in enumerate(best_clusters):
            keyaps  = [ x[1] for x in aps if x[0]==str(cid) ]
            keycfps = [ x for x in cfps if x[0]==cid ]
            keys.append([keyaps, keycfps])
        #print keys
        return [maxNI, keys]


    def _getKeyMACs(self, cids=None):
        table_name = 'wpp_clusteridaps'
        table_inst = self.tables[table_name]
        bc = [ str(x) for x in cids ]
        strWhere = "%s%s" % ("clusterid=", " or clusterid=".join(bc))
        #strWhere = "%s%s%s" % ("clusterid='", "' or clusterid='".join(bc), "'")
        sql = "SELECT * FROM %s WHERE (%s)" % (table_inst, strWhere)
        #print sql
        self.cur.execute(sql)
        return np.array(self.cur.fetchall())


    def _getFPs(self, cids=None):
        table_name = 'wpp_cfps'
        table_inst = self.tables[table_name]
        bc = [ str(x) for x in cids ]
        #strWhere = "%s%s%s" % ("clusterid='", "' or clusterid='".join(bc), "'")
        strWhere = "%s%s" % ("clusterid=", " or clusterid=".join(bc))
        sql = "SELECT * FROM %s WHERE (%s)" % (table_inst, strWhere)
        #print sql
        self.cur.execute(sql)
        return np.array(self.cur.fetchall())


    def _getBestCIDMaxNI(self, macs=None):
        table_name = 'wpp_clusteridaps'
        table_inst = self.tables[table_name]
        strWhere = "%s%s%s" % ("keyaps='", "' or keyaps='".join(macs), "'")
        if self.dbtype == 'postgresql':
            #sql = "SELECT cid,MAX(cidcnt) FROM (\
            #       SELECT clusterid AS cid, COUNT(clusterid) AS cidcnt \
            #       FROM %s WHERE (%s) GROUP BY cid) a,%s \
            #       WHERE cidcnt = (\
            #       SELECT MAX(cidcnt) as maxcidcnt FROM (\
            #       SELECT clusterid AS cid, COUNT(clusterid) AS cidcnt \
            #       FROM %s WHERE (%s) GROUP BY cid) b ) GROUP BY cid" % \
            #    (table_inst, strWhere, table_inst, table_inst, strWhere)
            sql = "SELECT clusterid AS cid, COUNT(clusterid) AS cidcnt \
                   FROM %s WHERE (%s) GROUP BY cid ORDER BY cidcnt desc" % \
                (table_inst, strWhere)
        elif self.dbtype == 'oracle':
            sql1 = self.sqls['SQL_SELECT'] % \
                ("clusterid cid, COUNT(clusterid) cidcnt", 
                 "%s where (%s) group by clusterid order by cidcnt desc) a, %s t \
                 where (a.cid=t.clusterid and a.cidcnt=%s) group by a.cid,a.cidcnt order by cidcnt desc" % \
                (table_inst, strWhere, table_inst))
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)
        #print sql
        self.cur.execute(sql)
        return np.array(self.cur.fetchall())


if __name__ == "__main__":
    if not len(sys.argv) == 2: 
        usage() 
        sys.exit(0)
    if sys.argv[1]:
        updb_opt = sys.argv[1]
        if updb_opt == 'call':
            wpp_tables['wpp_clusteridaps']='wpp_clusteridaps_all'
            wpp_tables['wpp_cfps']='wpp_cfps_all'
        elif updb_opt == 'cincr':
            wpp_tables['wpp_clusteridaps']='wpp_clusteridaps_incr'
            wpp_tables['wpp_cfps']='wpp_cfps_incr'
        elif updb_opt == 'uprecs':
            wpp_tables = {'wpp_uprecsinfo':'wpp_uprecsinfo',
                           'wpp_uprecsver':'wpp_uprecsver',
                        'wpp_uprecs_noloc':'wpp_uprecs_noloc'}
        elif updb_opt == 'normal':
            # ONLY load two algo tables: wpp_clusteridaps, wpp_cfps.
            pass
        else:
            print 'Unsupported db upload option: %s!' % updb_opt
            usage()
            sys.exit(0)
    else:
        print 'Unsupported db upload option: %s!' % updb_opt
        usage()
        sys.exit(0)

    dbips = DB_UPLOAD
    for svrip in dbips:
        dbsvr = dbsvrs[svrip]
        #print 'Loading data -> DB svr: %s' % svrip
        print '%s %s %s' % ('='*15, svrip, '='*15)
        wppdb = WppDB(dsn=dbsvr['dsn'],dbtype=dbsvr['dbtype'],tables=wpp_tables)
        wppdb.loadClusteredData(tbl_files)
        wppdb.close()
