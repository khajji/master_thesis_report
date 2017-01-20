#!/usr/bin/env python

import sys,os
import LogData_pb2
import gzip
import re
import glob
import json
import shutil
import logging
import time
from collections import defaultdict
from protobuf_to_dict import protobuf_to_dict
from boto.s3.connection import S3Connection
from boto.s3.key import Key
from importer import Importer

class MixsLogImporter(Importer):
    """
    Download mixs applicaton launch log from S3, save as raw data and as json and copy to hdfs
    """

    # conn
    conn = S3Connection()

    # base directory and pathes
    base_path = "/data/mixs_logs/"
    raw_log_dir = "raw"
    json_log_dir = "json"
    usrs_log_dir = "usrs"
    
    raw_log_path = "%s/%s" % (base_path, raw_log_dir)
    json_log_path = "%s/%s" % (base_path, json_log_dir)
    json_usrs_log_path = "%s/%s/%s" % (base_path, json_log_dir, usrs_log_dir)

    user = "mixs"
    hdfs_user_root = "/user/%s" % (user)
    mnt_point = "/mnt/hdfs/"
    hdfs_base_path = "%s/user/mixs/data/mixs_logs" % (mnt_point)
    hdfs_raw_log_path = "%s/%s" % (hdfs_base_path, raw_log_dir)
    hdfs_json_log_path = "%s/%s" % (hdfs_base_path, json_log_dir)
    hdfs_json_usrs_log_path = "%s/%s/%s" % (hdfs_base_path, json_log_dir, usrs_log_dir)
    
    # bucket filters (OR condition)
    TEST_BUCKET_NAME = "generaluploaderlogs0001"
    BUCKET_NAME_MAIN_1 = "atddisdmonster"
    bucket_filters = [BUCKET_NAME_MAIN_1]

    # file filters (OR condition)
    VA_WIDGET_LOGGER = "VAWidgetLogger"
    VA_LAUNCHER_LOGGER = "VALauncherLogger"
    file_filters = [VA_WIDGET_LOGGER]
    file_suffix_excluders = ["_0.out.gz"]

    # idx
    # 0 is GUP-generated-id-based (=~ imei-based) user, 3 is uuid-based user.
    user_idx = 0
    
    # extension
    OUT_GZ_EXTENSION = "out.gz"

    def __init__(self, raw_log_path = raw_log_path, json_usrs_log_path = json_usrs_log_path, conn = conn, bucket_filters = bucket_filters, file_filters = file_filters):
        """
        init

        Arguments:
        - `raw_log_path`: raw data path
        - `json_usrs_log_path`: json data path
        - `conn`: connection to S3
        - `bucket_filters`: bucket filters
        - `file_filters`: file filters
        """

        super(MixsLogImporter, self).__init__(raw_log_path, json_usrs_log_path, conn, bucket_filters, file_filters)

        logger = logging.getLogger("MixsLogImporter")
        logger.setLevel(logging.INFO)
        logging.basicConfig()
        self.logger = logger

        self.logger.info("init starts")
        self.raw_log_path = raw_log_path
        self.json_usrs_log_path = json_usrs_log_path
        self.conn = conn
        self.bucket_filters = bucket_filters
        self.file_filters = file_filters
        pass

    def imports(self, ):
        """
        download and import raw logs.
        """

        self.logger.info("import starts")
        st = time.time()

        all_buckets = self._get_all_buckets()
        buckets = self._get_buckets(all_buckets, self.bucket_filters)
        local_files = self._get_local_files(self.raw_log_path)

        # filterd buckets
        for bucket in buckets:
            self.logger.info(bucket)
            all_keys = self._get_all_keys(bucket)
            keys = self._get_keys(all_keys, self.file_filters)
            for key in keys: # filterd keys
                self.logger.info(key)
                filename = key.name.split("/")[-1]
                if filename not in local_files:
                    self.logger.info("processing %s" % (filename))
                    # download
                    raw_file_path = self._download(key, self.raw_log_path)
                    # to json
                    json_file_path = self._save_as_json(key, self.raw_log_path, self.json_usrs_log_path)
                    # push to hdfs
                    #push_to_hdfs(raw_file_path, "/%s/%s" % (hdfs_user_root, self.raw_file_path))
                    #push_to_hdfs(json_file_path, "/%s/%s" % (hdfs_user_root, json_file_path))
                    pass
                pass
            pass

        et = time.time()
        self.logger.info("total time: %f[s]" % (et-st))
        self.logger.info("import finished")


    def _save_as_json(self, key, raw_log_path, json_usrs_log_path):
        """
        save data to file out path as json format
        
        Arguments:
        - `key`: boto key object
        - `raw_log_path`: raw log path
        - `json_usrs_log_path`: json usrs log path
        """
        self.logger.info("save_as_json starts")
        src_filename = key.name.split("/")[-1]
        for file_suffix_excluder in self.file_suffix_excluders:
            if src_filename.endswith(file_suffix_excluder):
                return ""
            pass

        elms = src_filename.split("_")
                
        guid = elms[self.user_idx] # guid generated by UUID.random() or index of imei
        src_file_path = "%s/%s/%s" % (raw_log_path, guid, src_filename)

        # ungzip
        fpin = gzip.open(src_file_path, "rb")
        content = fpin.read()
        fpin.close()
        #content = content.decode('utf-8') # TODO: required to supress error?
        
        # deseriazlie
        log_datas = LogData_pb2.LogDatas()
        log_datas.ParseFromString(content)

        # to dict
        log_datas_dict = protobuf_to_dict(log_datas)

        # to json
        log_datas_json = json.dumps(log_datas_dict)
        
        # save

        dst_filename = "%s.json" % src_filename.split(".%s" % self.OUT_GZ_EXTENSION)[0]
        guid_path = "%s/%s" % (json_usrs_log_path, guid)
        dst_file_path = "%s/%s/%s" % (json_usrs_log_path, guid, dst_filename)

        if self.user_idx == 0: # imei
            imei = log_datas_dict["baseInfo"][1]["value"]
            guid_path = "%s/%s" % (json_usrs_log_path, imei)
            dst_file_path = "%s/%s/%s" % (json_usrs_log_path, imei, dst_filename)
            pass
        
        if not os.path.exists(guid_path):
            os.mkdir(guid_path)
            self._save(log_datas_json, dst_file_path)
        else:
            self._save(log_datas_json, dst_file_path)
            pass
        self.logger.info("save_as_json finished")
        return dst_file_path
    
    def _save(self, data, fout):
        """
        save data to file out path
        
        Arguments:
        - `data`: data
        - `fout`: file out path
        """
        self.logger.info("save starts")
        fpout = open(fout, "w")
        fpout.write(data)
        fpout.close()
        self.logger.info("save finished")
        pass


    def _download(self, key, raw_log_path = raw_log_path):
        """
        download a log specified by key to raw_log_path
        
        Arguments:
        - `raw_log_path`:
        - `key`:
        """
        self.logger.info("download starts")
        key_filename = key.name.split("/")[-1]
        elms = key_filename.split("_")
        guid = elms[self.user_idx]
        
        guid_path = "%s/%s" % (raw_log_path, guid)
        self.logger.info(guid_path)
        file_path = "%s/%s/%s" % (raw_log_path, guid, key_filename)
        self.logger.info(file_path)
        if not os.path.exists(guid_path):
            os.mkdir(guid_path)
            fpout = open(file_path, "w")
            key.get_file(fpout)
            fpout.close()
        else:
            fpout = open(file_path, "w")
            key.get_file(fpout)
            fpout.close()
            pass
        self.logger.info("download finished")
        return file_path

    def _get_local_files(self, raw_log_path = raw_log_path):
        """
        get local files on raw log directory

        Arguments:
        - `raw_log_path`:
        
        """
        self.logger.info("get_local_files starts")
        filepathes = glob.glob("%s/*/*" % (raw_log_path)) # e.g, #/data/mixs_log/raw/uid/filename
        local_files = {}
        for filepath in filepathes:
            filename = filepath.split("/")[-1]
            local_files[filename] = 1
            pass
        self.logger.info("get_local_files finished")
        return local_files

    def _get_keys(self, all_keys, file_filters = []):
        """
        
        Arguments:
        - `all_keys`:
        - `file_filters`:
        """
        self.logger.info("get_keys starts")

        file_filter_regexes = []
        for file_filter in file_filters:
            file_filter_regexes.append(re.compile("^.*%s.*\.%s$" % (file_filter, self.OUT_GZ_EXTENSION)))
            pass
        
        keys = []
        for key in all_keys:
            for file_filter_regex in file_filter_regexes:
                matcher = file_filter_regex.match(key.name)
                if matcher != None:
                    keys.append(key)
                    pass
                pass
            pass
        self.logger.info("get_keys finished")
        return keys

    def _get_buckets(self, all_buckets, bucket_filters = []):
        """
        filter for bucket and return bucket
        Arguments:
        - `all_buckets`:
        - `bucket_filters`:
        """
        self.logger.info("get_buckets_starts")

        # should be refactored
        bucket_filter_regexes = []
        for bucket_filter in bucket_filters:
            bucket_filter_regexes.append(re.compile("^.*%s.*$" % (bucket_filter)))
            pass

        buckets = []
        for bucket in all_buckets:
            for bucket_filter_regex in bucket_filter_regexes:
                matcher = bucket_filter_regex.match(bucket.name)
                if matcher != None:
                    buckets.append(bucket)
                    pass
                pass
            pass
        self.logger.info("get_buckets_finished")
        return buckets
        
    def _get_all_keys(self, bucket, prefix = "logs_001"):
        """
        return keys for bucket
        
        Arguments:
        - `bucket`: bucket
        """
        self.logger.info("_get_all_keys starts")
        all_keys = []
        # all_keys = bucket.get_all_keys(prefix = prefix) # max_keys_limit = 1000
        for key in bucket.list():
            all_keys.append(key)
        self.logger.info("_get_all_keys finished")
        return all_keys

    def _get_all_buckets(self, ):
        """
        return all bucket
        """
        self.logger.info("_get_all_buckets starts")
        all_buckets = self.conn.get_all_buckets()
        self.logger.info("_get_all_buckets finished")
        return all_buckets
    
    def push_to_hdfs(self, src, dst):
        """
        push local logs to hdfs
        """
        self.logger.info("push_to_hdfs starts")
        os.system("hadoop fs -cp %s %s" % (src, dst))
        #shutil.copy(src, dst)
        self.logger.info("push_to_hdfs finished")
        pass

def main():
    raw_log_path = "/home/kzk/project/mixs/data/mixs_logs_20140904/raw"
    json_usrs_log_path = "/home/kzk/project/mixs/data/mixs_logs_20140904/json/usrs"
    
    importer = MixsLogImporter(raw_log_path = raw_log_path, json_usrs_log_path = json_usrs_log_path)
    importer.imports()

    # elapsed time: 485.772666 [s] on 2014/09/04

if __name__ == '__main__':
    main()

    