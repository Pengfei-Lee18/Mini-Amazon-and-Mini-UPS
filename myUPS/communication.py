import os
from unicodedata import name
from setuptools import Command 
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myUPS.settings")
from django.db import transaction
from django.db.models import Q
import django 
if django.VERSION >= (1, 7):
    django.setup()
from upswebsite.models import DeliveringTruck, Product, User,Package,Truck,Ack,Sequence

from multiprocessing import cpu_count
import world_ups_pb2 as World_Ups
import UA_pb2 as UA
import tools
import time

seqnum = 0

##commuication with World_Ups
def UConnect_obj():
    connect = World_Ups.UConnect()
    # connect.worldid = int(input("please enter the worldid: ").strip())
    truck_raw_list = input("please enter the truck: ").split()
    truck_list =[truck_raw_list[i:i+2] for i in range(0,len(truck_raw_list),2)]
    
    for truck_num in truck_list:
        truck = connect.trucks.add()
        cur_truck = Truck.objects.create(truck_package_number=0, status='idle')
        truck.id = int(cur_truck.truck_id)
        truck.x = int(truck_num[0])
        truck.y = int(truck_num[1])
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

def UsendArrive_obj(truck_id):
    message = UA.UAmessage()
    sendarrive = message.send_arrive
    sendarrive.truck_id = truck_id
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


def UResponse_obj(buf_message,s,s_amazon):
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
        print("type")
        print(type(each_ack))
        try:
            if Ack.objects.filter(seqnum=each_ack):
                print("已经有这个ack了")
                continue   
            else:
                print("正在创建新的ack")
                Ack.objects.create(seqnum=each_ack)
                print("创建了新的ack")
        except Exception as ex:
            print(ex)
    
    for each_delivered in response.delivered:
        if Sequence.objects.filter(seq=each_delivered.seqnum):
            continue   
        else:
            tools.send_message(s,Ack_obj(each_delivered.seqnum))
            Sequence.objects.create(seq=each_delivered.seqnum)
        cur_package = Package.objects.get(shipment_id=each_delivered.packageid)
        cur_package.status = 'delivered'
        cur_package.save()
        truck = Truck.objects.get(truck_id=each_delivered.truckid)
        truck.truck_package_number -= 1
        truck.status = 'delivering'
        truck.save()
        print("更改状态为delivering")
        #发给amazon,改改socket
        message = UpacDelivered_obj(each_delivered.packageid)
        tools.send_message(s_amazon,message) #要改

    for each_complete in response.completions:   #for pickup response
        # 去掉已经处理过的sequencenumber
        print("完成状态")
        try:
            if Sequence.objects.filter(seq=each_complete.seqnum):
                continue
            else:
                tools.send_message(s,Ack_obj(each_complete.seqnum))
                Sequence.objects.create(seq=each_complete.seqnum)
        except Exception as ex:
            print("在完成的地方报错")
            print(ex)
        truck = Truck.objects.get(truck_id=each_complete.truckid)
        if(each_complete.status=='ARRIVE WAREHOUSE'):
            print("到了warehouse")
            delivering_truck = DeliveringTruck.objects.get(truck=truck)
            delivering_truck.delete()
            truck.status = 'loading'
            truck.save()
            print("更改了状态为loading")
            # 发给amazon,改改socket
            message = UsendArrive_obj(truck.truck_id) #给amz发消息说到了,准备load 但是package的状态在那里改成loading？？
            tools.send_message(s_amazon,message) #要改
            print("给amz发消息说到了")
            packagelist = Package.objects.filter(truck = truck, status = 'pick_up')
            for package in packagelist:
                package.status = 'loading'
                package.save()
            print("更改完了package的状态为loading")
        else:
            truck.status = 'idle'
            truck.save()
            print("更改了状态为idle")

    # for each_status in response.truckstatus:
    #     if Sequence.objects.filter(seq=each_status.seqnum):
    #         continue   
    #     else:
    #         tools.send_message(s,Ack_obj(each_status.seqnum))
    #         Sequence.objects.create(seq=each_status.seqnum)
    #     #待定功能，可能用于在后台自动刷新数据中的truck位置和状态。数据库需要加trcuk坐标
    #     # p = Process(target=updateTruck,args=())
    #     # p.start()
    #     continue

    # if response.HasField('finished'):
    #     #关闭世界
    #     if response.finished:
    #         closeworld(s)

    

    # for each_err in response.error:
    #     if Sequence.objects.filter(seq=each_err.seqnum):
    #         continue   
    #     else:
    #         tools.send_message(s,Ack_obj(each_err.seqnum))
    #         Sequence.objects.create(seq=each_err.seqnum)
    #     print(each_err.seqnum, " error occur: ",each_err.error)

    return 

def closeworld(s):
    print("closeworld")
    s.close()
    return
#Communication with Amazon

def AResponse(buf_message,s,s_amazon):
    print("AResponse,multiple process")
    print(buf_message,s,s_amazon)
    global seqnum
    response = UA.AUmessage()
    response.ParseFromString(buf_message)
    print(response)
    #是有一个pickup请求
    if response.HasField('pickup'):
        truck = None
        print("pickup has field")
        whid = response.pickup.whid
        shipment_id = response.pickup.shipment_id
        x = response.pickup.x
        y = response.pickup.y
        #如果有车正在去这个wh
        if DeliveringTruck.objects.filter(whid = whid):
            print("delivering truck")
            truck = DeliveringTruck.objects.get(whid = whid).truck
            truck.truck_package_number += 1
            truck.save()
        else:
            #找一个可用状态的卡车 并且他的包裹在里面是最小的
            print("find truck")
            truck_list = Truck.objects.filter(Q (status = 'delivering')| Q (status = 'idle') )
            print(truck_list)
            while(not truck_list):
                print('enter while:')
                time.sleep(0.5)
                truck_list = Truck.objects.filter(Q (status = 'delivering')| Q (status = 'idle') )
            truck = truck_list.order_by('truck_package_number')[0]
            print(truck)
            truck.status = 'traveling'
            DeliveringTruck.objects.create(truck=truck,whid=whid)
            print("truck.truck_package_number")
            truck.truck_package_number += 1
            truck.save()
            print("truck.truck_package_number")
            seqnum += 1
            cur_seq = seqnum
            print("seqnum:",seqnum)
            command = UGoPickup_obj(truck.truck_id,whid,cur_seq)
            print("command:",command)
            result = Ack.objects.filter(seqnum=cur_seq)
            #另开进程?

            print("send command")
            print(command)
            while(not result):
                print('send commend, ack not received')
                tools.send_message(s,command)
                print(command)
                time.sleep(2)
                result = Ack.objects.filter(seqnum=cur_seq)
            print("收到了world回来的ack")
        #根据可选用户名字段，判断有没有这个用户，并且生成对应的package，并且返回response
        if response.pickup.HasField('ups_username'):
            print("要开始发了,给amz")
            print("ups_username has field")
            ups_username = response.pickup.ups_username
            if User.objects.filter(name = ups_username):
                cur_user = User.objects.get(name = ups_username)
                print("user has field")
                package = Package.objects.create(shipment_id=shipment_id,user_id = cur_user,x=x,y=y,status='pick_up',truck = truck)
                response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,True)
            else:
                print("user not exist, truck id =")
                print(truck.truck_id)
                try:
                    package = Package.objects.create(shipment_id=shipment_id,x=x,y=y,status='pick_up',truck = truck)
                    response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,False)
                except Exception as ex:
                    print("在生成包裹的时候报错")
                    print(ex)

        else:
            print("ups_username has no field")
            package = Package.objects.create(shipment_id=shipment_id,x=x,y=y,status='pick_up',truck = truck)
            response = UPacPickupRes_obj(package.tracking_id,package.truck.truck_id,package.shipment_id,False)
        try:
        #给amazon端口发消息，改改socket
            print("send message to amazon")
            tools.send_message(s_amazon,response)
            package.save()
        except Exception as ex:
            print("在发送消息的时候报错")
            print(ex)
        
    
    if response.HasField('all_loaded'):
        try:
            print("all_loaded has field")
            truck_id = response.all_loaded.truck_id
            print("遍历package  ")
            seqnum += 1
            cur_seq2 = seqnum
            # 暂且这样写，后面再改
            command = World_Ups.UCommands()
            go_deliver = command.deliveries.add()
            go_deliver.truckid = truck_id
            go_deliver.seqnum = cur_seq2
            for package in response.all_loaded.packages:
                shipment_id = package.shipment_id
                cur_package = Package.objects.get(shipment_id=shipment_id)
                cur_package.status = 'delivering'
                item = package.item
                cur_package.save()
                print("遍历item")
                for each_item in item:
                    product_id = each_item.product_id
                    description = each_item.description
                    count = each_item.count
                    Product.objects.create(shipment_id = shipment_id, product_id = product_id, description = description, count = count)
                location = go_deliver.packages.add()
                location.packageid = shipment_id
                location.x = package.x
                location.y = package.y
                
                # command = UGoDeliver_obj(truck_id,shipment_id,package.x,package.y,cur_seq2)
            result = Ack.objects.filter(seqnum=cur_seq2)
            print("又要开始循环发送了")
            print(command)
            while(not result):
                print("一直在发")
                tools.send_message(s,command)
                time.sleep(2)
                result = Ack.objects.filter(seqnum=cur_seq2)
            print("收到了world回来的ack")
            truck = Truck.objects.get(truck_id = truck_id)
            if truck.status == 'loading':
                truck.status = 'delivering'
            truck.save()
            print("load完事了")
        except Exception as ex:
            print("all_loaded报错")
            print(ex)
    # if response.HasField('bind_upsuser'):
    #     print("bind_upsuser has field")
    #     shipment_id = response.bind_upsuser.shipment_id
    #     username = response.bind_upsuser.ups_username
    #     package = Package.objects.get(shipment_id=shipment_id)
    #     if package.user_id == None:
    #         if User.objects.get(name = username).exists():
    #             package.user_id = response.bind_upsuser.ups_username
    #             bind_res = UBindRes_obj(shipment_id,True)
    #         else:
    #             bind_res = UBindRes_obj(shipment_id,False)
    #         package.save()
    #     else:
    #         bind_res = UBindRes_obj(shipment_id,False)
    #     #给amazon端口发消息，改改socket
    #     tools.send_message(s_amazon,bind_res)
    return