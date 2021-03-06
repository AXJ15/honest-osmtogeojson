#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os, gc, sys, shelve
import xml.etree.ElementTree as ET
from os import path, remove
from sys import getsizeof
from contextlib import closing as CL
from hotgj.helpers import *

DEFAULT_IN_MEMORY_SIZE = '300'
DEFAULT_DB_FILE = 'temp.db'
DEFAULT_SKIP_TAGS = ['source', 'source_ref', 'source:ref', 'history', 'attribution', 'created_by', 'tiger:county', 'tiger:tlid', 'tiger:upload_uuid']
DEFAULT_META_ATTR = ['user', 'uid', 'timestamp', 'visible', 'changeset']
OSM = 'osm'
BOUNDS = 'bounds'
NODE = 'node'
WAY = 'way'
RELATION = 'relation'
TAG = 'tag'
ND = 'nd'
MEMBER = 'member'
OSM_ALL_TAGS = [OSM, BOUNDS, NODE, WAY, RELATION, TAG, ND, MEMBER]
OSM_MAIN_TAGS = [NODE, WAY, RELATION]

class OSMIndexingException(Exception): pass
class OSMConvertingException(Exception): pass
class DBAccessException(Exception): pass

def get_db_file(_directory):
    return path.abspath(_directory +'/'+ DEFAULT_DB_FILE)

def reset_db_file(_directory):
    _path = get_file_path(_directory +'/'+ DEFAULT_DB_FILE)
    try:
        if _path is not None: remove(_path)
    except OSError as e:
        raise DBAccessException(e)
    return

def update_db_file(_directory, func):
    _path = get_db_file(_directory= _directory)
    try:
        with CL(shelve.open(_path, 'c')) as db:
            if callable(func):
                func(db= db)
    except IOError as e:
        raise DBAccessException('db access error: '+ DEFAULT_DB_FILE +', details: ' + str(e))
    return

def store_dect_to_db(_directory, _dict, bag):
    def func(db):
        for key in _dict:
            if key in db: db[key] = deduplicator(db[key])
            else: db[key] = _dict[key]
            loading_bag = loading(bag= bag, atxt= 'dumping data to file: temp.db, ' + str(key))
    return update_db_file(_directory= _directory, func= func)

def store_list_to_db(_directory, _list, _pos, bag):
    def func(db):
        for key in _list:
            list_id = format_in_db_list_id(key, _pos[key])
            db[list_id] = _list[key]
            _list[key] = []
            _pos[key] += 1
            loading_bag = loading(bag= bag, atxt= 'dumping data to file: temp.db, ' + str(key))
        db['elements-count'] = _pos
    return update_db_file(_directory= _directory, func= func)

def format_in_db_dict_id(elm):
    return elm.tag + '/' + elm.attrib['id']

def format_in_db_list_id(key, pos):
    return key + '/' + str(pos)

def stream_osm_file(_path):
    stack = []
    for event, element in ET.iterparse(_path, events=('start', 'end')):
        if event == 'start':
            parent = stack[-1] if len(stack) > 0 else None
            stack.append(element)
            yield element, parent
        else:
            stack.pop()
            element.clear()
    return

def deduplicator(objA, objB):
    verA = parse_int(objA['attrib']['version'])
    verB = parse_int(objB['attrib']['version'])
    return objA if verA >= verB else objB

def is_same_version(objA, prt):
    verA = parse_int(objA['attrib']['version'])
    verB = parse_int(prt.attrib['version'])
    return True if verA == verB else False

def OSM_handler(elm, prt, _dict, _list):
    if elm.tag == OSM and prt == None:
        _dict['osm'] = { 'attrib': dict(elm.attrib) }
        return True
    return

def BOUNDS_handler(elm, prt, _dict, _list):
    if prt == None: return
    if elm.tag == BOUNDS and prt.tag == OSM:
        for i in ['maxlon', 'minlon', 'maxlat', 'minlat']:
            if i not in elm.attrib:
                raise OSMIndexingException('element is missing important attributes: '+ str(elm))
        _dict['bounds'] = { 'attrib': dict(elm.attrib) }
        return True
    return

def OSM_MAIN_TAGS_handler(elm, prt, _dict, _list):
    if prt == None: return
    if elm.tag in OSM_MAIN_TAGS and prt.tag == OSM:
        buk = []
        if elm.tag == NODE: buk = list(i for i in ['id', 'version', 'lon', 'lat'] if i not in elm.attrib)
        elif elm.tag in [WAY, RELATION]: buk = list(i for i in ['id', 'version'] if i not in elm.attrib)
        if len(buk) != 0:
            raise OSMIndexingException('element is missing important attributes: '+ str(elm))
        elm_id = format_in_db_dict_id(elm)
        if elm_id in _dict:
            _dict[elm_id] = deduplicator(_dict[elm_id], { 'attrib': dict(elm.attrib) })
        else:
            _list[elm.tag + 's'].append(elm.attrib['id'])
            _dict[elm_id] = { 'attrib': dict(elm.attrib) }
        return True
    return

def TAG_handler(elm, prt, _dict, _list):
    if prt == None: return
    if elm.tag == TAG and prt.tag in OSM_MAIN_TAGS:
        for i in ['k', 'v']:
            if i not in elm.attrib:
                raise OSMIndexingException('element is missing important attributes: '+ str(elm))
        prt_id = format_in_db_dict_id(prt)
        if is_same_version(_dict[prt_id], prt):
            if 'properties' not in _dict[prt_id]:
                _dict[prt_id]['properties'] = {}
            _dict[prt_id]['properties'][elm.attrib['k']] = elm.attrib['v']
        return True
    return

def ND_handler(elm, prt, _dict, _list):
    if prt == None: return
    if elm.tag == ND and prt.tag == WAY:
        if 'ref' not in elm.attrib:
            raise OSMIndexingException('element is missing important attributes: '+ str(elm))
        prt_id = format_in_db_dict_id(prt)
        if 'nodes' not in _dict[prt_id]:
            _dict[prt_id]['nodes'] = []
        _dict[prt_id]['nodes'].append(elm.attrib['ref'])
        return True
    return

def MEMBER_handler(elm, prt, _dict, _list):
    if prt == None: return
    if elm.tag == MEMBER and prt.tag == RELATION:
        for i in ['role', 'type', 'ref']:
            if i not in elm.attrib:
                raise OSMIndexingException('element is missing important attributes: '+ str(elm))
        prt_id = format_in_db_dict_id(prt)
        if 'members' not in _dict[prt_id]:
            _dict[prt_id]['members'] = []
        _dict[prt_id]['members'].append(dict(elm.attrib))
        return True
    return

def get_default_element_handlers():
    return [OSM_handler, BOUNDS_handler, OSM_MAIN_TAGS_handler, TAG_handler, ND_handler, MEMBER_handler]

def index_osm_file(osm_path, destination, in_memory_dict_size):
    osm = stream_osm_file(osm_path)
    in_memory_allowed_size = in_memory_dict_size * 100 * 1024
    in_memory_dict = {}
    in_memory_list = {'nodes': [], 'ways': [], 'relations': []}
    in_memory_list_pos = { 'nodes': 0, 'ways': 0, 'relations': 0 }
    loading_bag = {}

    for element, parent in osm:
        if element.tag in OSM_MAIN_TAGS:
            if getsizeof(in_memory_dict) > in_memory_allowed_size:
                store_list_to_db(_directory= destination, _list= in_memory_list, _pos= in_memory_list_pos, bag= loading_bag)
                store_dect_to_db(_directory= destination, _dict= in_memory_dict, bag= loading_bag)
                in_memory_dict = {}
                gc.collect()
        try:
            consumed = None
            for fn in get_default_element_handlers():
                if callable(fn):
                    consumed = fn(element, parent, in_memory_dict, in_memory_list)
                    if consumed == True: break
            if consumed == None:
                raise OSMIndexingException('unidentified element, element ignored: '+ str(element))
            loading_bag = loading(bag= loading_bag, atxt= str(element))
        except OSMIndexingException as e:
            print(ERROR, e)

    store_list_to_db(_directory= destination, _list= in_memory_list, _pos= in_memory_list_pos, bag= {})
    store_dect_to_db(_directory= destination, _dict= in_memory_dict, bag= {})
    return

def convert_osm_file(db_path, skip_tags):
    return


