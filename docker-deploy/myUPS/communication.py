import os
from re import U, X
from unicodedata import name
from setuptools import Command 
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myUPS.settings")
from django.conf import settings
from django.db import transaction
from django.db.models import Q
import django 
if django.VERSION >= (1, 7):
    django.setup()
from upswebsite.models import DeliveringTruck, Product, User,Package,Truck,Ack,Sequence,World, Resend
from multiprocessing import cpu_count
import world_ups_pb2 as World_Ups
import UA_pb2 as UA
import tools
import time
import threading

lock=threading.Lock()
seq_lock=threading.Lock()
socket_amazon = None
seqnum = 0

def init_trucks_world(world_id):
    print("in init_trucks_world_id")
    truck_list = Truck.objects.filter(world_id=0)
    for truck in truck_list:
        truck.world_id = world_id
        truck.save()
    World.objects.create(world_id=world_id)

##commuication with World_Ups
def UConnect_obj():
    connect = World_Ups.UConnect()
    # connect.worldid = int(input("please enter the worldid: ").strip())

#initialize method 1
    while(1):
        truck_number = input("please enter the number of trucks(all trucks initialize at (0,0)): ").strip()
        if truck_number.isdigit():
            truck_number = int(truck_number)
            print(truck_number)
            if truck_number > 0:
                for i in range(truck_number):
                    truck = connect.trucks.add()
                    cur_truck = Truck.objects.create(truck_package_number=0, status='idle')
                    truck.id = int(cur_truck.truck_id)
                    truck.x = 0
                    truck.y = 0
                break
        print('plase enter the right format!')
            


#initialize method 2
    # truck_raw_list = input("please enter the truck: ").split()
    # truck_list =[truck_raw_list[i:i+2] for i in range(0,len(truck_raw_list),2)]

    # for truck_num in truck_list:
    #     truck = connect.trucks.add()
    #     cur_truck = Truck.objects.create(truck_package_number=0, status='idle')
    #     truck.id = int(cur_truck.truck_id)
    #     truck.x = int(truck_num[0])
    #     truck.y = int(truck_num[1])

    connect.isAmazon = False
    return connect


def UGoPickup_obj(truck_id,whid,seqnum): #truck_id, warehouse_id
    print("in UGoPickup_obj:")
    command = World_Ups.UCommands()
    gopickup = command.pickups.add()
    gopickup.truckid = truck_id
    gopickup.seqnum = seqnum
    gopickup.whid = whid
    # command.pickups.append(
    #     command.UGoPickup(truck_id=truck_id,whid=whid,seqnum=seqnum)
    # )
    return command

def UGoDeliver_obj(truck_id,package_id,x,y,seqnum): #truck_id, package_id, x, y
    command = World_Ups.UCommands()
    go_deliver = command.deliveries.add()
    go_deliver.truckid = truck_id
    go_deliver.seqnum = seqnum
    location = go_deliver.packages.add()
    location.packageid = package_id
    location.x = x
    location.y = y
    return command

def Simspeed_obj(speed):
    command = World_Ups.UCommands()
    command.simspeed = speed
    return command

def UDisconnect_obj():
    command = World_Ups.UCommands()
    command.disconnect = True
    return command

def UQuery_obj(truck_id,seqnum):
    command = World_Ups.UCommands()
    query = command.queries.add()
    query.truckid = truck_id
    query.seqnum = seqnum
    return command

def Ack_obj(seqnum):
    command = World_Ups.UCommands()
    command.acks.append(seqnum)
    return command

# def updateTruck():
#     trucklist = Truck.object.all()
#     while True:
#         for truck in trucklist:
            
#     pass

def USendWorldId_obj(worldid):
    message = UA.UAmessage()
    sendworld_id = message.world_id
    sendworld_id.world_id = worldid
    return message

def UPacPickupRes_obj(tracking_id,truck_id,shipment_id,is_binded):
    print("in UPacPickupRes_obj:")
    print(tracking_id,truck_id,shipment_id,is_binded)
    message = UA.UAmessage()
    pickupres = message.pickup_res
    pickupres.tracking_id = tracking_id
    pickupres.truck_id = truck_id
    pickupres.is_binded = is_binded
    pickupres.shipment_id = shipment_id
    return message

def UsendArrive_obj(truck_id,x,y):
    message = UA.UAmessage()
    sendarrive = message.send_arrive
    sendarrive.truck_id = truck_id
    sendarrive.x = x
    sendarrive.y = y
    return message

def UpacDelivered_obj(shipment_id):
    message = UA.UAmessage()
    delivered = message.pac_delivered
    delivered.shipment_id = shipment_id
    return message

def UBindRes_obj(shipment_id,is_binded):
    message = UA.UAmessage()
    bindres = message.bind_res
    bindres.shipment_id = shipment_id
    bindres.is_binded = is_binded
    return message

def UResendPackage_obj(shipment_id):
    message = UA.UAmessage()
    resendpackage = message.resend_package
    resendpackage.shipment_id = shipment_id
    return message

def resend_package(conn, world_id):
    while True:
        resendlist = Resend.objects.filter(world_id=world_id)
        for resend in resendlist:
            response = UResendPackage_obj(resend.shipment_id)
            print("resend package:")
            print(response)
            tools.send_message(conn,response)
            resend.delete()
            time.sleep(0.3)
        time.sleep(5)

def ACK_find(seqnum, world_id):
    while(True):
        print("in ACK_find")
        print(seqnum)
        ack = Ack.objects.filter(seqnum=seqnum, world_id=world_id)
        if ack:
            break
        time.sleep(0.7)

def send_email(email, track_num, locationx, locationy):

    from django.core.mail import EmailMultiAlternatives
    print("??????")
    subject = '''your order has been delivered'''

    text_content = '''your order has been delivered'''

    html_content = '''
                    <p>your order has been delivered, here is detailed information</p>
                    <p>Tracking Number: {}</p>
                    <p>Destination: ({},{})</p>
                    '''.format(track_num, locationx, locationy)

    msg = EmailMultiAlternatives(subject, text_content, settings.EMAIL_HOST_USER, [email])
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def request_send(s, message, stop_signal):
    while (not stop_signal):
        print("in request_send")
        print(message)
        tools.send_message(s, message)
        time.sleep(5)
    print("?????????request_send")

def UResponse_obj(buf_message,s,s_amazon,world_id):
    print("UResponse,multiple process")
    print(buf_message,s,s_amazon)
    global seqnum
    response = World_Ups.UResponses()
    response.ParseFromString(buf_message)
    print("response:")
    print(response)
    print("response.acks:\n")
    print(response.acks)
    for each_ack in response.acks:
        print("--------------------ack:",each_ack)
        # print("type")
        print(type(each_ack))
        try:
            if Ack.objects.filter(seqnum=each_ack, world_id=world_id):
                print("???????????????ack???")
                continue   
            else:
                print("??????????????????ack")
                Ack.objects.create(seqnum=each_ack, world_id=world_id)
                print("???????????????ack")
        except Exception as ex:
            print(ex)
    
    for each_delivered in response.delivered:
        try:
            print("--------------delivered ??????-------------")
            if Sequence.objects.filter(seq=each_delivered.seqnum, world_id=world_id):
                continue   
            else:
                tools.send_message(s,Ack_obj(each_delivered.seqnum))
                Sequence.objects.create(seq=each_delivered.seqnum, world_id=world_id)
            cur_package = Package.objects.get(shipment_id=each_delivered.packageid, world_id=world_id)
            cur_package.status = 'delivered'
            cur_package.save()
            truck = Truck.objects.get(truck_id=each_delivered.truckid, world_id=world_id)
            truck.truck_package_number -= 1
            truck.status = 'delivering'
            truck.save()
            print("???????????????delivering")
            #??????amazon,??????socket
            message = UpacDelivered_obj(each_delivered.packageid)
            tools.send_message(s_amazon,message) #??????
            email = cur_package.user_id.email
            track_num = cur_package.tracking_id
            locationx = cur_package.x
            locationy = cur_package.y
            send_email(email, track_num, locationx, locationy)
        except Exception as ex:
            print("delivered ??????")
            print(ex)

    for each_complete in response.completions:   #for pickup response
        try:
            # ????????????????????????sequencenumber
            print("-------------- ??????????????????/??????warehouse-------------")
            print("????????????")
            try:
                if Sequence.objects.filter(seq=each_complete.seqnum, world_id=world_id):
                    continue
                else:
                    tools.send_message(s,Ack_obj(each_complete.seqnum))
                    Sequence.objects.create(seq=each_complete.seqnum, world_id=world_id)
            except Exception as ex:
                print("????????????????????????")
                print(ex)
            truck = Truck.objects.get(truck_id=each_complete.truckid,world_id=world_id)
            x = each_complete.x
            y = each_complete.y
            if(each_complete.status=='ARRIVE WAREHOUSE'):
                print("??????warehouse")
                delivering_truck = DeliveringTruck.objects.get(truck=truck,world_id=world_id)
                delivering_truck.delete()
                truck.status = 'loading'
                truck.save()
                print("??????????????????loading")
                # ??????amazon,??????socket
                message = UsendArrive_obj(truck.truck_id,x,y) #???amz??????????????????,??????load ??????package????????????????????????loading??????
                tools.send_message(s_amazon,message) #??????
                print("??????????????????amazon?????????",message)
                print("???amz??????????????????")
                truck = Truck.objects.get(truck_id=each_complete.truckid,world_id=world_id)
                packagelist = Package.objects.filter(truck = Truck.objects.get(truck_id=each_complete.truckid,world_id=world_id), status = 'pick_up', world_id=world_id)
                print(packagelist)
                print(truck.truck_id)
                for package in packagelist:
                    print(package.tracking_id)
                    package.status = 'loading'
                    package.save()
                print("????????????package????????????loading")
            else:
                truck.status = 'idle'
                truck.save()
                print("??????????????????idle")
        except Exception as ex:
            print("complete ??????")
            print(ex)

    # for each_status in response.truckstatus:
    #     if Sequence.objects.filter(seq=each_status.seqnum, world_id=world_id):
    #         continue   
    #     else:
    #         tools.send_message(s,Ack_obj(each_status.seqnum))
    #         Sequence.objects.create(seq=each_status.seqnum, world_id=world_id)
    #     #????????????????????????????????????????????????????????????truck????????????????????????????????????trcuk??????
    #     # p = Process(target=updateTruck,args=())
    #     # p.start()
    #     continue

    # if response.HasField('finished'):
    #     #????????????
    #     if response.finished:
    #         closeworld(s)

    

    for each_err in response.error:
        if Sequence.objects.filter(seq=each_err.seqnum, world_id=world_id):
            continue   
        else:
            tools.send_message(s,Ack_obj(each_err.seqnum))
            Sequence.objects.create(seq=each_err.seqnum, world_id=world_id)
        print(each_err.seqnum, " error occur: ",each_err.error)

    return 

def closeworld(s):
    print("closeworld")
    s.close()
    return
#Communication with Amazon


def AResponse(buf_message,s,s_amazon,world_id):
    # global socket_amazon
    # socket_amazon = s_amazon
    stop_signal = []
    stop_signal2 = []
    print("AResponse,multiple process")
    print(buf_message,s,s_amazon)
    global seqnum
    response = UA.AUmessage()
    response.ParseFromString(buf_message)
    print(response)
    #????????????pickup??????
    if response.HasField('pickup'):
        try:
            print("--------------pickup ????????????-------------")
            truck = None
            whid = response.pickup.whid
            shipment_id = response.pickup.shipment_id
            x = response.pickup.x
            y = response.pickup.y
            package = None ###########################
            #???????????????????????????wh
            if DeliveringTruck.objects.filter(whid = whid,world_id=world_id):
                print("delivering truck")
                truck = DeliveringTruck.objects.get(whid = whid,world_id=world_id).truck
                truck.truck_package_number += 1
                truck.save()
            else:
                lock.acquire() 
                #?????????????????????????????? ???????????????????????????????????????
                print("find truck")
                truck_list = Truck.objects.filter((Q (status = 'delivering')| Q (status = 'idle') ) & Q (world_id=world_id))
                print(truck_list)
                while(not truck_list):
                    print('enter while:')
                    time.sleep(0.5)
                    truck_list = Truck.objects.filter((Q (status = 'delivering')| Q (status = 'idle') ) & Q (world_id=world_id))
                truck = truck_list.order_by('truck_package_number')[0]
                print(truck)
                truck.status = 'traveling'
                DeliveringTruck.objects.create(truck=truck,whid=whid,world_id=world_id)
                truck.truck_package_number += 1
                truck.save()
                lock.release() 
                seq_lock.acquire() 
                seqnum += 1
                seq_lock.release() 
                cur_seq = seqnum
                print("seqnum:",seqnum)
                command = UGoPickup_obj(truck.truck_id,whid,cur_seq)
                print("command:",command)
                result = Ack.objects.filter(seqnum=cur_seq,world_id=world_id)
                #?????????????

                print("send command")
                print(command)
                ###########################
                package = Package.objects.create(shipment_id=shipment_id,x=x,y=y,status='pick_up',truck = truck,world_id=world_id)

                # while(not result):
                '''
                ????????????????????????????????????
                ?????????????????????????????????ack????????????????????????????????? join??????????????????????????????
                '''
                
                thread1 = threading.Thread(target=request_send, args=(s,command,stop_signal,))
                thread2 = threading.Thread(target=ACK_find, args=(cur_seq,world_id,))
                # print('send commend, ack not received')
                # tools.send_message(s,command)
                # print(command)
                #result = Ack.objects.filter(seqnum=cur_seq,world_id=world_id)
                # time.sleep(5)
                thread1.start()
                thread2.start()
                thread2.join()
                stop_signal.append(1)


                print("?????????world?????????ack")
            #?????????????????????????????????????????????????????????????????????????????????package???????????????response
            if response.pickup.HasField('ups_username'):
                print("???????????????,???amz")
                print("ups_username has field")
                # try:
                #     # user = User.objects.create(name = "test",password = "testpassword",email = "xq47@duke.edu")
                #     # user = User.objects.create(name = "test1",password = "testpassword1",email = "xushanqing797@gmail.com")
                
                # except Exception as ex:
                #     print("????????????????????????")
                #     print(ex)
                # print("??????????????????")
                ups_username = response.pickup.ups_username
                if User.objects.filter(name = ups_username,world_id=world_id):
                    cur_user = User.objects.get(name = ups_username,world_id=world_id)
                    print("user has field")
                    try:
                        # package = Package.objects.create(shipment_id=shipment_id,user_id = cur_user,x=x,y=y,status='pick_up',truck = truck,world_id=world_id)
                        package.user_id = cur_user
                        package.save()
                        response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,True)
                    except Exception as ex:
                        print("??????????????????????????????????????????")
                        print(ex)
                else:
                    print("user not exist, truck id =")
                    print(truck.truck_id)
                    try:
                        # package = Package.objects.create(shipment_id=shipment_id,x=x,y=y,status='pick_up',truck = truck,world_id=world_id)
                        response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,False)
                    except Exception as ex:
                        print("??????????????????????????????")
                        print(ex)
            else:
                print("ups_username has no field")
                # package = Package.objects.create(shipment_id=shipment_id,x=x,y=y,status='pick_up',truck = truck,world_id=world_id)
                response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,False)
            
            #???amazon????????????????????????socket
            print("send message to amazon")
            tools.send_message(s_amazon,response)
            
        except Exception as ex:
            print("???pickup???????????????")
            print(ex)
        
    
    if response.HasField('all_loaded'):
        print("--------------all loaded ????????????-------------")
        try:
            print("all_loaded has field")
            truck_id = response.all_loaded.truck_id
            print("??????package  ")
            seq_lock.acquire() 
            seqnum += 1
            seq_lock.release() 
            cur_seq2 = seqnum
            # ??????????????????????????????
            command = World_Ups.UCommands()
            go_deliver = command.deliveries.add()
            go_deliver.truckid = truck_id
            go_deliver.seqnum = cur_seq2
            for package in response.all_loaded.packages:
                shipment_id = package.shipment_id
                cur_package = Package.objects.get(shipment_id=shipment_id,world_id=world_id)
                cur_package.status = 'delivering'
                item = package.item
                cur_package.save()
                print("??????item")
                for each_item in item:
                    product_id = each_item.product_id
                    description = each_item.description
                    count = each_item.count
                    Product.objects.create(shipment_id = shipment_id, product_id = product_id, description = description, count = count,world_id=world_id)
                location = go_deliver.packages.add()
                location.packageid = shipment_id
                location.x = cur_package.x
                location.y = cur_package.y
                
                # command = UGoDeliver_obj(truck_id,shipment_id,package.x,package.y,cur_seq2)
            result = Ack.objects.filter(seqnum=cur_seq2,world_id=world_id)
            print("???????????????????????????")
            print(command)
            # while(not result):


                # print("????????????")
                # tools.send_message(s,command)
                # time.sleep(5)
                # result = Ack.objects.filter(seqnum=cur_seq2,world_id=world_id)
            
            thread3 = threading.Thread(target=request_send, args=(s,command,stop_signal2,))
            thread4 = threading.Thread(target=ACK_find, args=(cur_seq2,world_id,))
            thread3.start()
            thread4.start()
            thread4.join()
            stop_signal2.append(1)


            print("?????????world?????????ack")
            truck = Truck.objects.get(truck_id = truck_id,world_id=world_id)
            if truck.status == 'loading':
                truck.status = 'delivering'
            truck.save()
            print("load?????????")
        except Exception as ex:
            print("all_loaded??????")
            print(ex)

    if response.HasField('bind_upsuser'):
    
        print("bind_upsuser has field")
        try:
            shipment_id = response.bind_upsuser.shipment_id
            print("shipment_id = ",shipment_id)
            username = response.bind_upsuser.ups_username
            print("username = ",username)
            package = Package.objects.get(shipment_id=shipment_id,world_id=world_id)
            print("package = ",package)
            if package.user_id == None:
                if User.objects.filter(name = username,world_id=world_id):
                    cur_user = User.objects.get(name = username,world_id=world_id)
                    print("user exist,change user of the package")
                    package.user_id = cur_user
                    bind_res = UBindRes_obj(shipment_id,True)
                    print("????????????????????????")
                else:
                    bind_res = UBindRes_obj(shipment_id,False)
                    print("????????????????????????")
                package.save()
            else:
                bind_res = UBindRes_obj(shipment_id,False)
        except Exception as ex:
            print("bind_upsuser??????")
            print(ex)
        #???amazon????????????????????????socket
        tools.send_message(s_amazon,bind_res)
    time.sleep(6)
    return