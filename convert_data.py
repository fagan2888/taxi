#!/usr/bin/env python
import os, h5py, csv, sys, numpy, theano, ast
from fuel.converters.base import fill_hdf5_file

test_size = 320 # `wc -l test.csv` - 1 # Minus 1 to ignore the header
train_size = 1710670 # `wc -l train.csv` - 1

stands_size = 63 # `wc -l metaData_taxistandsID_name_GPSlocation.csv` - 1
taxi_id_size = 448 # `cut -d, -f 5 train.csv test.csv | sort -u | wc -l` - 1
origin_call_size = 57124 # `cut -d, -f 3 train.csv test.csv | sort -u | wc -l` - 3 # Minus 3 to ignore "NA", "" and the header

Call_type = h5py.special_dtype(enum=(numpy.int8, {'CENTRAL': 0, 'STAND': 1, 'STREET': 2}))
Day_type = h5py.special_dtype(enum=(numpy.int8, {'NORMAL': 0, 'HOLYDAY': 1, 'HOLYDAY_EVE': 2}))
Polyline = h5py.special_dtype(vlen=theano.config.floatX)

taxi_id_dict = {}
origin_call_dict = {0: 0}

def get_unique_taxi_id(val):
    if val in taxi_id_dict:
        return taxi_id_dict[val]
    else:
        taxi_id_dict[val] = len(taxi_id_dict)
        return len(taxi_id_dict) - 1

def get_unique_origin_call(val):
    if val in origin_call_dict:
        return origin_call_dict[val]
    else:
        origin_call_dict[val] = len(origin_call_dict)
        return len(origin_call_dict) - 1

def read_stands(input_directory, h5file):
    stands_name = numpy.empty(shape=(stands_size+1,), dtype=('a', 24))
    stands_latitude = numpy.empty(shape=(stands_size+1,), dtype=theano.config.floatX)
    stands_longitude = numpy.empty(shape=(stands_size+1,), dtype=theano.config.floatX)
    stands_name[0] = 'None'
    stands_latitude[0] = stands_longitude[0] = 0
    with open(os.path.join(input_directory, 'metaData_taxistandsID_name_GPSlocation.csv'), 'r') as f:
        reader = csv.reader(f)
        reader.next() # header
        for line in reader:
            id = int(line[0])
            stands_name[id] = line[1]
            stands_latitude[id] = float(line[2])
            stands_longitude[id] = float(line[3])
    return (('stands', 'stands_name', stands_name),
            ('stands', 'stands_latitude', stands_latitude),
            ('stands', 'stands_longitude', stands_longitude))

def read_taxis(input_directory, h5file, dataset):
    print >> sys.stderr, 'read %s: begin' % dataset
    size=globals()['%s_size'%dataset]
    trip_id = numpy.empty(shape=(size,), dtype='S19')
    call_type = numpy.empty(shape=(size,), dtype=Call_type)
    origin_call = numpy.empty(shape=(size,), dtype=numpy.int32)
    origin_stand = numpy.empty(shape=(size,), dtype=numpy.int8)
    taxi_id = numpy.empty(shape=(size,), dtype=numpy.int16)
    timestamp = numpy.empty(shape=(size,), dtype=numpy.int32)
    day_type = numpy.empty(shape=(size,), dtype=Day_type)
    missing_data = numpy.empty(shape=(size,), dtype=numpy.bool)
    latitude = numpy.empty(shape=(size,), dtype=Polyline)
    longitude = numpy.empty(shape=(size,), dtype=Polyline)
    with open(os.path.join(input_directory, '%s.csv'%dataset), 'r') as f:
        reader = csv.reader(f)
        reader.next() # header
        id=0
        for line in reader:
            if id%10000==0 and id!=0:
                print >> sys.stderr, 'read %s: %d done' % (dataset, id)
            trip_id[id] = line[0]
            call_type[id] = ord(line[1][0]) - ord('A')
            origin_call[id] = 0 if line[2]=='NA' or line[2]=='' else get_unique_origin_call(int(line[2]))
            origin_stand[id] = 0 if line[3]=='NA' or line[3]=='' else int(line[3])
            taxi_id[id] = get_unique_taxi_id(int(line[4]))
            timestamp[id] = int(line[5])
            day_type[id] = ord(line[6][0]) - ord('A')
            missing_data[id] = line[7][0] == 'T'
            polyline = ast.literal_eval(line[8])
            latitude[id] = numpy.array([point[1] for point in polyline], dtype=theano.config.floatX)
            longitude[id] = numpy.array([point[0] for point in polyline], dtype=theano.config.floatX)
            id+=1
    splits = ()
    print >> sys.stderr, 'read %s: writing' % dataset
    for name in ['trip_id', 'call_type', 'origin_call', 'origin_stand', 'taxi_id', 'timestamp', 'day_type', 'missing_data', 'latitude', 'longitude']:
        splits += ((dataset, name, locals()[name]),)
    print >> sys.stderr, 'read %s: end' % dataset
    return splits

def unique(h5file):
    unique_taxi_id = numpy.empty(shape=(taxi_id_size,), dtype=numpy.int32)
    assert len(taxi_id_dict) == taxi_id_size
    for k, v in taxi_id_dict.items():
        unique_taxi_id[v] = k

    unique_origin_call = numpy.empty(shape=(origin_call_size+1,), dtype=numpy.int32)
    assert len(origin_call_dict) == origin_call_size+1
    for k, v in origin_call_dict.items():
        unique_origin_call[v] = k

    return (('unique_taxi_id', 'unique_taxi_id', unique_taxi_id),
            ('unique_origin_call', 'unique_origin_call', unique_origin_call))

def convert(input_directory, save_path):
    h5file = h5py.File(save_path, 'w')
    split = ()
    split += read_stands(input_directory, h5file)
    split += read_taxis(input_directory, h5file, 'train')
    print 'First origin_call not present in training set: ', len(origin_call_dict)
    split += read_taxis(input_directory, h5file, 'test')
    split += unique(h5file)

    fill_hdf5_file(h5file, split)

    for name in ['stands_name', 'stands_latitude', 'stands_longitude']:
        h5file[name].dims[0].label = 'index'
    for name in ['trip_id', 'call_type', 'origin_call', 'origin_stand', 'taxi_id', 'timestamp', 'day_type', 'missing_data', 'latitude', 'longitude']:
        h5file[name].dims[0].label = 'batch'
    h5file['unique_taxi_id'].dims[0].label = 'unormalized taxi_id'
    h5file['unique_origin_call'].dims[0].label = 'unormalized origin_call'

    h5file.flush()
    h5file.close()

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print >> sys.stderr, 'Usage: %s download_dir output_file' % sys.argv[0]
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
