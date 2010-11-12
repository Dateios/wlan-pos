#!/usr/bin/env python
import sys
import os
import csv
import pprint
import numpy as np
import cx_Oracle as ora
import psycopg2 as pg

from config import tbl_names, tbl_field, tbl_forms, tbl_idx, tbl_files, \
        dsn_local_ora, dsn_vance_ora, dsn_local_pg, dbtype_ora, dbtype_pg, sqls


class WppDB(object):
    def __init__(self,dsn=None,tbl_names=tbl_names,tbl_field=None,tbl_forms=None,sqls=None,
            tbl_files=None,tbl_idx=None,dbtype=None):
        if not dsn: sys.exit('Need DSN info!')
        if not dbtype: sys.exit('Need DB type!') 
        self.dbtype = dbtype
        if self.dbtype == 'oracle':
            try:
                self.con = ora.connect(dsn) #'yxt/yxt@localhost:1521/XE'
            except ora.DatabaseError, e:
                sys.exit('\nERROR: %s' % e)
        elif self.dbtype == 'postgresql':
            try:
                self.con = pg.connect(dsn) #"host=localhost dbname=wppdb user=yxt password=yxt port=5433"
                self.con.set_isolation_level(pg.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            except Exception, e:
                sys.exit('\nERROR: %d: %s\n' % (e.pgcode, e.pgerror))
        else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)

        if not tbl_field or not tbl_forms or not tbl_names:
            sys.exit('Need name, field, format definition for all tables!')
        self.tbl_names = tbl_names
        self.tbl_field = tbl_field
        self.tbl_forms = tbl_forms
            
        if not sqls: sys.exit('Need sql set!')
        self.sqls = sqls

        self.tbl_files = tbl_files
        self.tbl_idx = tbl_idx

        self.cur = self.con.cursor()

    def close(self):
        self.cur.close()
        self.con.close()

    def getCIDcount(self, macs=None):
        if not macs: sys.exit('Need macs!')
        strWhere = "%s%s%s" % ("keyaps='", "' or keyaps='".join(macs), "'")
        sql = self.sqls['SQL_SELECT'] % ("clusterid, count(clusterid) cmask", 
                "wpp_clusteridaps where (%s) group by clusterid order by cmask desc"%strWhere)
        print sql
        self.cur.execute(sql)
        return self.cur.fetchall()

    def load_tables(self, tbl_files=None):
        if not self.tbl_files: 
            if not tbl_files:
                sys.exit('\nERROR: %s: Need a csv file!\n' % csvfile)
            else: self.tbl_files = tbl_files
        else: pass

        for table in self.tbl_names:
            csvfile = self.tbl_files[table]
            if not os.path.isfile(csvfile):
                sys.exit('\n%s is NOT a file!' % (csvfile))
            #
            print 'TRUNCATE TABLE: %s' % table
            self.cur.execute(self.sqls['SQL_TRUNCTB'] % table)
            #
            #print 'DROP TABLE: %s' % table
            #self.cur.execute(self.sqls['SQL_DROPTB'] % table)
            #print 'CREATE TABLE: %s' % table
            #self.cur.execute(self.sqls['SQL_CREATETB'] % \
            #        (table, self.tbl_forms[table]))
            if self.dbtype == 'oracle':
                # Import csv data.
                csvdat = csv.reader( open(csvfile,'r') )
                try:
                    indat = [ line for line in csvdat ]
                except csv.Error, e:
                    sys.exit('\nERROR: %s, line %d: %s!\n' % (csvfile, csvdat.line_num, e))
                print 'csv data %d records.' % len(indat)

                self._insertMany(table=table, indat=indat)
            elif self.dbtype == 'postgresql':
                self.cur.copy_from(file(csvfile), table, ',')
            else: sys.exit('\nERROR: Unsupported DB type: %s!' % self.dbtype)

            self.cur.execute(self.sqls['SQL_SELECT'] % ('COUNT(*)', table))
            print 'Total %s rows in %s now.' % (self.cur.fetchone()[0], table)
            #if self.tbl_idx:
            #    for col_name in self.tbl_idx[table]:
            #        # index naming rule: i_tablename_colname.
            #        idx_name = 'i_%s_%s' % (table, col_name)
            #        self.cur.execute(self.sqls['SQL_CREATEIDX'] % \
            #                (idx_name, table, col_name))
            #        print self.sqls['SQL_CREATEIDX'] % (idx_name,table,col_name)
            print '-'*40

        self.con.commit()

    def _getNewCid(self):
        sql = sqls['SQL_SELECT'] % ('max(clusterid)', 'wpp_clusteridaps')
        self.cur.execute(sql)
        cid = self.cur.fetchone()[0] + 1
        return cid

    def _insertMany(self, table=None, indat=None):
        table_field = self.tbl_field[table]
        num_fields = len( table_field.split(',') )
        bindpos = '(%s)' % ','.join( ':%d'%(x+1) for x in xrange(num_fields) )
        #print bindpos
        self.cur.prepare(self.sqls['SQL_INSERT'] % (table, table_field, bindpos))
        self.cur.executemany(None, indat)
        print 'Add %d rows to |%s|' % (self.cur.rowcount, table)
        self.con.commit()

    def addCluster(self, macs=None):
        table = 'wpp_clusteridaps'
        cid = self._getNewCid()
        cidmacseq = []
        for seq,mac in enumerate(macs):
            cidmacseq.append([ cid, mac, seq+1 ])
        #print cidmacseq
        self._insertMany(table=table, indat=cidmacseq)
        return cid

    def addFps(self, cid=None, fps=None):
        table = 'wpp_cfps'
        cids = np.array([ [cid] for i in xrange(len(fps)) ])
        fps = np.array(fps)
        cidfps = np.append(cids, fps, axis=1).tolist()
        #print cidfps
        self._insertMany(table=table, indat=cidfps)

    def getCIDcntMaxSeq(self, macs=None):
        table = 'wpp_clusteridaps'
        table_field = self.tbl_field[table]
        if not type(macs) is list: 
            macs = list(macs)
        if not len(macs):
            sys.exit('Invalid macs!')
        strWhere = "%s%s%s" % ("keyaps='", "' or keyaps='".join(macs), "'")
        sql1 = self.sqls['SQL_SELECT'] % ("clusterid cid, count(clusterid) cidcnt", 
            "%s where (%s) group by clusterid order by cidcnt desc) a, \
            %s t where a.cid=t.clusterid  group by a.cid,a.cidcnt order by cidcnt desc"%(table,strWhere,table))
        sql = self.sqls['SQL_SELECT'] % ("cid,cidcnt,max(t.seq)", "(%s"%sql1)
        self.cur.execute(sql)
        return self.cur.fetchall()


if __name__ == "__main__":
    pp = pprint.PrettyPrinter(indent=2)

    #tbl_names = ('tsttbl',)
    tbl_names = ('wpp_clusteridaps','wpp_cfps')
    wppdb = WppDB(dsn=dsn_local_ora, dbtype=dbtype_ora, tbl_idx=tbl_idx, sqls=sqls, 
            tbl_names=tbl_names,tbl_field=tbl_field,tbl_forms=tbl_forms['oracle'])
    wppdb.load_tables(tbl_files)
    wppdb.close()
