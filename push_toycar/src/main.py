#!/home/gloria/anaconda3/envs/py3_8_env/bin/python3
# -*- coding: utf-8 -*-

import os
import cv2
import threading
import time
import numpy as np
import queue

import rospy
from detect_torch import ToyCar
from camera.camera_model import CameraModel
from camera.camera_capture import CameraCap
from create_msgs.msg import laser2map
from std_msgs.msg import Header
from visualization_msgs.msg import Marker
from geometry_msgs.msg import Twist, Vector3

import actionlib
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import Pose, Point, Quaternion, PoseStamped
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal

from scipy.spatial.transform import Rotation as R

SHOW = True

def main():
    rospy.init_node("detect_toycar")

    detect_param = rospy.get_param("~detect")
    camera_param = rospy.get_param("~camera")
    camera_param_root = rospy.get_param("~camera_param_root")
    docking_toycar_params = rospy.get_param("~docking_toycar")
    find_toycar_params = rospy.get_param("~find_toycar")
    detect_interval = rospy.get_param("~detect_interval")
    final_goal = rospy.get_param("~final_goal")
    start_point = rospy.get_param("~start_point")
    use_move_base = rospy.get_param("~use_move_base")

    far_cap = CameraCap('far_camera',camera_param,camera_param_root)
    near_cap = CameraCap('near_camera',camera_param,camera_param_root)

    detect = ToyCar(**detect_param)

    push_toycar(detect,far_cap,near_cap,find_toycar_params,docking_toycar_params,final_goal, use_move_base,start_point=start_point)

class push_toycar():
    def __init__(self,detect, far_cap, near_cap,find_toycar_params,docking_toycar_params,final_goal, use_move_base,start_point=None):
        self.detect = detect
        self.far_cap = far_cap
        self.near_cap = near_cap
        self.find_toycar_params = find_toycar_params
        self.final_goal = final_goal


        if use_move_base:
            self.move_base = actionlib.SimpleActionClient("/move_base", MoveBaseAction)
            self.move_base.wait_for_server(rospy.Duration(5))
        else:
            self.move_base = None

        if start_point is None:
            RT = self.RT.get()
            theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
            cur_pose = [RT.T, theta]
            self.start_point = cur_pose
        else:
            self.start_point = start_point

        self.cmd_vel_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)

        self.docking_toycar_params = docking_toycar_params

        self.RT = queue.Queue(10)
        threads = [threading.Thread(target=self.listen_RT)]
        threads.append(threading.Thread(target=self.run))
        try:
            for t in threads:
                t.start()
        finally:
            twist = Twist()
            twist.linear = Vector3(0, 0, 0)
            twist.angular = Vector3(0, 0, 0)
            self.cmd_vel_pub.publish(twist)

    def run(self):
        self.window_name = 'test_windows'
        cv2.namedWindow(self.window_name, 0)
        while not rospy.is_shutdown():
            # find toy car
            map_pos = self.find_toycar()
            if map_pos is None:
                break
            print('Finded toycar and start to move to toycar')
            # move to 15cm away from toy car
            self.move(map_pos)
            print('arrival position and start to dock ')
            # dock toy car and robot
            self.docking_toycar()
            print('docked toycar  and start push toycar to target position')
            # push to goal
            self.push2target()
            print('fininsh push ')
            # back to start
            self.move2start_point()
            print('arrival start point !')

    def move2start_point(self,max_time = 360):
        # back to start
        # move 10cm backwards
        move_dis = 0.1
        RT = self.RT.get()
        theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
        start_pose = [RT.T, theta]
        max_x_vel = 0.1
        cur_x_vel = 0
        acc_lim_x = 0.1/5
        while not rospy.is_shutdown():
            RT = self.RT.get()
            theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
            cur_pose = [RT.T, theta]
            if np.linalg.norm(np.array(cur_pose[0])-np.array(start_pose[0]))<move_dis*0.8:
                cur_x_vel = max(max_x_vel,cur_x_vel+acc_lim_x)
            else:
                if cur_x_vel<=0:
                    return True
                cur_x_vel = cur_x_vel-acc_lim_x
            twist = Twist()
            twist.linear = Vector3(-cur_x_vel, 0, 0)
            twist.angular = Vector3(0, 0, 0)
            self.cmd_vel_pub.publish(twist)
            time.sleep(0.1)


        # move to start
        move = control_move([self.start_point[:3],self.start_point[3:]], self.cmd_vel_pub, move_base=self.move_base)
        t = 0
        while not rospy.is_shutdown() and t < max_time:
            RT = self.RT.get()
            theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
            cur_pose = [RT.T, theta]
            state = move.run(cur_pose)
            if state:
                print('target arrival')
                return True
            t += 1
            if self.move_base:
                time.sleep(1)
            else:
                time.sleep(0.1)  # 10hz
        print('move2start_point:out of time !')

    def callback(self,data,q):
        q.put(data)
        q.get() if q.qsize()>1 else time.sleep(0.02)

    def listen_RT(self,):
        rospy.Subscriber("laser2map", laser2map, self.callback,self.RT)
        rospy.spin()

    def move(self,pos,max_time = 360):
        '''
        obtain the location of toycar
           move to t_dis away from and face toycar, near camera detect
        '''


        RT = self.RT.get()
        T_= RT.T
        t_dis = 0.30
        dis = ((T_[0]-pos[0])**2+(T_[1]-pos[1])**2)**0.5
        # make sure moving distance > distance to target
        assert dis>t_dis
        ratio = t_dis/dis
        move_pose_position = [(T_[0]-pos[0])*ratio+pos[0],(T_[1]-pos[1])*ratio+pos[1],0]

        theta = np.arccos((pos[0]-T_[0])/dis)
        if pos[1]-T_[1]<0:
            theta = np.pi*2-theta
        r = R.from_euler('zxy',(theta,0,0))
        move_pose_orientation = r.as_quat()


        move = control_move([move_pose_position,move_pose_orientation],self.cmd_vel_pub, move_base = self.move_base)
        t = 0
        while not rospy.is_shutdown() and t<max_time:
            RT = self.RT.get()
            theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
            cur_pose = [RT.T, theta]
            state = move.run(cur_pose)
            if state:
                break
            t+=1
            if self.move_base:
                time.sleep(1)
            else:
                time.sleep(0.1) # 10hz

        self.far_cap.close()
        self.near_cap.open()

        # check with near camera
        img = self.near_cap.read()
        box, conf = self.detect.run(img)
        for b in box:
            cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 254, 0), 1)
        if SHOW:
            cv2.imshow(self.window_name, img)
            cv2.waitKey(1)
        if len(box)>0:
            return True
        else:
            rospy.logerr(' Near Camera No Find Toycar ')
            rospy.logerr(' maybe toycar position is wrong ')

    def find_toycar(self):
        '''
        explore with designated rountine and detect toy car
            rotate to check around???
            explore with designated rountine (get param from patrol_route)
            if no toy car found, end
        '''
        self.far_cap.open()
        self.target_check = target_check(final_goal=self.final_goal)

        # find toy car
        # stage 1 rotate
        cur_turn = 0.1
        max_turn = 0.5

        RT = self.RT.get()
        init_theta = R.from_matrix(np.array(RT.R).reshape(3,3)).as_euler('zxy',degrees=True)
        #self.near_cap.releaase()
        while not rospy.is_shutdown():
            twist = Twist()
            twist.linear = Vector3(0,0,0)
            if cur_turn>=max_turn:
                twist.angular = Vector3(0, 0, cur_turn)
            else:
                cur_turn = cur_turn + 0.01
                twist.angular = Vector3(0, 0, cur_turn)

            # detct
            #print('to get image')
            img = self.far_cap.read()
            if img is None:
                print('far image is None')
                if self.near_cap.read()[0] is None:
                    print('near image is None')
            box,conf = self.detect.run(img)
            #print(box,conf)
            for b in box:
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 254, 0), 1)
            if SHOW:
                cv2.imshow(self.window_name, img)
                cv2.waitKey(1)
            #
            RT = self.RT.get()
            if len(box)>0:
                points = [[[(b[0] + b[2]) / 2, b[3]]] for b in box]
                pos = self.far_cap.get_position(points)
                R_ = np.array(RT.R).reshape(3,3)
                T_ = np.array(RT.T).reshape(3,1)
                map_pos = [(R_.dot(p)+T_).flatten().tolist() for p in np.array(pos).reshape(-1,3,1)]
                if self.target_check.update(RT.header.stamp.to_sec(),map_pos):
                    return self.target_check.get_target()
            cur_theta = R.from_matrix(np.array(RT.R).reshape(3,3)).as_euler('zxy',degrees=True)


            if cur_theta[0] >=(init_theta[0]-5) and cur_theta[0] - init_theta[0]>340:
                break
            elif cur_theta[0] <(init_theta[0]-5) and (180- init_theta[0])+(cur_theta[0]+180)>340:
                break
            self.cmd_vel_pub.publish(twist)
        # pause
        while cur_turn>0:
            twist = Twist()
            twist.linear = Vector3(0, 0, 0)
            cur_turn = min(cur_turn - 0.01, 0)
            twist.angular = Vector3(0, 0, cur_turn)

            # detect
            img = self.far_cap.read()
            box,conf = self.detect.run(img)
            for b in box:
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 254, 0), 1)
            if SHOW:
                cv2.imshow(self.window_name, img)
                cv2.waitKey(1)
            #
            RT = self.RT.get()
            if len(box)>0:
                points = [[[(b[0] + b[2]) / 2, b[3]]] for b in box]
                pos = self.far_cap.get_position(points)
                R_ = np.array(RT.R).reshape(3,3)
                T_ = np.array(RT.T).reshape(3,1)
                map_pos = [(R_.dot(p)+T_).flatten().tolist() for p in np.array(pos).reshape(-1,3,1)]
                if self.target_check.update(RT.header.stamp.to_sec(), map_pos):
                    return self.target_check.get_target()

            self.cmd_vel_pub.publish(twist)

        print('Finish rotate (not found toycar) and start to patrol')
        # stage 2 explore with rountine
        for idx,tpose in enumerate(self.find_toycar_params['patrol_route']):
            move = control_move([tpose[:3],tpose[3:]],self.cmd_vel_pub,move_base=self.move_base)
            while not rospy.is_shutdown():
                RT = self.RT.get()
                theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
                cur_pose = [RT.T, theta]
                state = move.run(cur_pose)
                if state :
                    break
                # elif state == GoalStatus.ABORTED:
                #     self.move_base.send_goal(goal)

                # detect
                img = self.far_cap.read()
                box, conf = self.detect.run(img)

                for b in box:
                    cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 254, 0), 1)
                if SHOW:
                    cv2.imshow(self.window_name, img)
                    cv2.waitKey(1)
                
                if len(box) > 0:
                    points = [[[(b[0] + b[2]) / 2, b[3]]] for b in box]
                    pos = self.far_cap.get_position(points)
                    R_ = np.array(RT.R).reshape(3, 3)
                    T_ = np.array(RT.T).reshape(3, 1)
                    map_pos = [(R_.dot(p) + T_).flatten().tolist() for p in np.array(pos).reshape(-1, 3, 1)]
                    if self.target_check.update(RT.header.stamp.to_sec(), map_pos):
                        return self.target_check.get_target()

        rospy.logerr('finish patrol and  no found toycar')
        return None

    def docking_toycar(self):

        cur_turn = 0.1
        max_turn = 0.1
        cur_x = 0.05
        max_x = 0.1

        min_y = min(self.docking_toycar_params['left_port'][1],self.docking_toycar_params['left_port'][1])
        left_x = self.docking_toycar_params['left_port'][0]
        right_x = self.docking_toycar_params['right_port'][0]
        enter_y = self.docking_toycar_params['enter_port']

        while not rospy.is_shutdown():
            twist = Twist()
            twist.angular = Vector3(0, 0, 0)
            twist.linear = Vector3(0, 0, 0)

            img = self.near_cap.read()
            box, conf = self.detect.run(img,is_near=True)

            cv2.line(img, (left_x, 0), (left_x, img.shape[0]), (0,0,255), 2)
            cv2.line(img, (right_x, 0), (right_x, img.shape[0]), (0,0,255), 2)
            cv2.line(img, (0, enter_y), (img.shape[1],enter_y), (0,0,255), 2)
            for b in box:
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 254, 0), 1)
            if SHOW:
                cv2.imshow(self.window_name, img)
                cv2.waitKey(1)

            if len(box)>1:
                rospy.logerr('docking_toycar: %d toycar.'%(len(box)))
                box_dis = np.array(box)
                box_dis = box_dis.reshape(-1,2,2).mean(axis=1)
                box_dis = np.linalg.norm(box_dis-np.array([[img.shape[1]//2,img.shape[0]//2]]),axis=1)
                box = box[np.argmin(box_dis)]
            elif len(box)==0:
                rospy.logerr('docking_toycar: No toycar')
                continue
                # assert NotImplementedError
            else:
                box = box[0]
            if box[3]<min_y:
                if box[2]>right_x:
                    # left
                    twist.angular = Vector3(0, 0, -cur_turn)
                elif box[0]<left_x:
                    # right
                    twist.angular = Vector3(0, 0, cur_turn)
                else:
                    # forward
                    twist.linear = Vector3(cur_x, 0, 0)
            else:

                if box[2]<right_x and box[0]>left_x:
                    if box[1]>enter_y:
                        # finish
                        self.cmd_vel_pub.publish(twist)
                        self.near_cap.close()
                        return True
                    else:
                        # forward
                        twist.linear = Vector3(cur_x, 0, 0)
                else:
                    # bug
                    rospy.logwarn('docking_toycar: No toycar')
                    # backwards
                    twist.linear = Vector3(-cur_x, 0, 0)
            self.cmd_vel_pub.publish(twist)

        self.near_cap.close()

    def push2target(self,max_time=360):
        move = control_move([self.final_goal[:3],self.final_goal[3:]], self.cmd_vel_pub, move_base=self.move_base)
        t = 0
        while not rospy.is_shutdown() and t < max_time:
            RT = self.RT.get()
            theta = R.from_matrix(np.array(RT.R).reshape(3, 3)).as_euler('zxy')
            cur_pose = [RT.T, theta]
            state = move.run(cur_pose)
            if state:
                print('target arrival')
                return True
            t += 1
            if self.move_base:
                time.sleep(1)
            else:
                time.sleep(0.1)  # 10hz
        print('push2target???out of time !')

class target_check():
    def __init__(self, max_time= 1, max_distance = 0.1, min_target_times=1,final_goal = None,min_final_goal = 0.3):
        self.max_time = max_time # max interval
        self.min_target_times = min_target_times # min check times
        self.max_distance = max_distance # max distance
        self.target_info = []# [[time,[position]]]
        self.target_position = None

        # compute toy car's postition from designated goal (round robot's radius = 0.2)
        dis = 0.2
        theta = R.from_quat(final_goal[3:]).as_euler('zxy')[0]
        fx = final_goal[0]+np.cos(theta)*dis
        fy = final_goal[1]+np.sin(theta)*dis
        self.final_goal = np.array([fx,fy,0])
        self.min_final_goal = min_final_goal # disregard toy car with 0.3m around goal

    def get_target(self):
        return self.target_position

    def update(self, cur_time, position):
        # check time
        new_target_info = []
        for tinfo in self.target_info:
            if abs(cur_time-tinfo[0])<self.max_time:
                new_target_info.append(tinfo)

        # check distance
        self.target_info =new_target_info
        for pos in position:
            flag = 1
            for _,p in new_target_info:
                if self.check_distance(pos,p[-1]):
                    p.append(pos)
                    self.target_info.append([cur_time,p])
                    flag = 0
                    break
            if flag:
                self.target_info.append([cur_time,[pos]])
        return self.check()

    def check_distance(self,target,pred):
        dis = np.linalg.norm(np.array(target)-np.array(pred))
        if dis<=self.max_distance:
            return True
        else:
            return False

    def check(self):
        for _,p in self.target_info:
            if np.linalg.norm(np.array(p[-1])-self.final_goal)<=self.min_final_goal:
                continue
            if len(p)>=self.min_target_times:
                self.target_position = p[-1]
                return True
        return False

class control_move():
    def __init__(self,goal,cmd_publish, publish_temp_goal = None, move_base = None):
        # goal [[pos],[quat]]
        self.max_x_vel = 0.15
        # compute with 5hz
        self.acc_lim_x = 0.1/5
        self.max_theta_vel = 0.3

        self.acc_lim_theta = 0.1

        self.xy_goal_tolerance = 0.1
        self.yaw_goal_tolerance = 0.03


        # other params
        self.max_theta = 0.05 # rotate when delta theta > 0.05
        self.min_theta = 0.05 # move when delta theta < 0.05

        # whether to apply move_base
        self.move_base = move_base
        if self.move_base:
            self.move_base.cancel_goal()
            move_goal = MoveBaseGoal()
            header = Header(999, rospy.Time.now(), 'map')
            move_goal.target_pose.header = header
            move_goal.target_pose.pose = Pose(Point(*goal[0]), Quaternion(*goal[1]))
            self.move_base.send_goal(move_goal)
        else:
            goal[1] = R.from_quat(goal[1]).as_euler('zxy')
            self.goal = goal
        # state
        self.cur_x_vel = 0
        self.cur_theta_vel = 0
        self.state = 'init' # {'init'???'arrival'???only position reached???'finish'???both position and orientation reached, 'move', 'stop', 'turn'}
        self.cmd_publish = cmd_publish
        self.publish_temp_goal = publish_temp_goal

    def run(self,cur_pose):
        if self.move_base:
            state = self.move_base.get_state()
            return state == GoalStatus.SUCCEEDED
        else:
            return self.move(cur_pose)

    def move(self, cur_pose):
        '''
        -- if orientation is detour, rotate
        -- if orientation is correct, move
           oscillate may happen
        '''
        theta, dis = self.compute_theta(self.goal, cur_pose)
        # print(self.state)
        if self.state == 'init':
            # initial pose
            # check distance
            if dis<self.xy_goal_tolerance:
                if abs(theta)<self.yaw_goal_tolerance:
                    self.state = 'finish'
                else:
                    self.state = 'arrival'
            else:
                if abs(theta)<self.min_theta:
                    self.state = 'move'
                else:
                    self.state = 'turn'

        elif self.state == 'arrival':
            # reach goal position, rotate to reach angle
            theta = self.goal[1][0]-cur_pose[1][0]
            if abs(theta) < self.yaw_goal_tolerance:
                print('finish')
                self.state = 'finish'
            else:
                if theta > 0:
                    self.cur_theta_vel = max(min(self.cur_theta_vel, self.cur_theta_vel + self.acc_lim_theta),self.acc_lim_theta)
                else:
                    self.cur_theta_vel = -max(min(self.cur_theta_vel, self.cur_theta_vel + self.acc_lim_theta),self.acc_lim_theta)

        elif self.state == 'finish':
            # reach goal
            return True

        elif self.state == 'move':
            if dis<self.xy_goal_tolerance:
                self.cur_x_vel = max(0,self.cur_x_vel-self.acc_lim_x)
                if self.cur_x_vel>0:
                    print(' arrival but vel is not zero: vel ',self.cur_x_vel)
                    self.state = 'stop'
                else:
                    print(' arrival  position')
                    self.state = 'arrival'
            else:
                if abs(theta) >= self.max_theta:
                    # detour
                    self.state = 'stop'
                    self.cur_x_vel = max(0, self.cur_x_vel - self.acc_lim_x)
                else:
                    if dis<=(self.cur_x_vel**2)/self.acc_lim_x/2:
                        # nearby
                        self.cur_x_vel = min(self.cur_x_vel-self.acc_lim_x,self.acc_lim_x)
                    else:
                        self.cur_x_vel = min(self.max_x_vel , self.cur_x_vel+self.acc_lim_x)

        elif self.state == 'stop':
            if self.cur_x_vel>0:
                self.cur_x_vel = max(0, self.cur_x_vel - self.acc_lim_x)
            else:
                self.state = 'turn'
                if theta > 0:
                    self.cur_theta_vel = min(self.cur_theta_vel, self.cur_theta_vel + self.acc_lim_theta)
                else:
                    self.cur_theta_vel = min(self.cur_theta_vel, self.cur_theta_vel - self.acc_lim_theta)

        elif self.state == 'turn':
            if abs(theta)<self.min_theta:
                self.cur_theta_vel = 0
                self.state = 'move'
            else:
                if theta > 0:
                    self.cur_theta_vel = max(min(self.cur_theta_vel, self.cur_theta_vel + self.acc_lim_theta),self.acc_lim_theta)
                else:
                    self.cur_theta_vel = -max(min(self.cur_theta_vel, self.cur_theta_vel + self.acc_lim_theta),self.acc_lim_theta)
        else:
            print('the state is error',self.state)

        if self.state == 'finish':
            twist = Twist()
            twist.linear = Vector3(0, 0, 0)
            twist.angular = Vector3(0, 0, 0)
            self.cmd_publish.publish(twist)
            return True
        else:
            twist = Twist()
            twist.linear = Vector3(self.cur_x_vel, 0, 0)
            twist.angular = Vector3(0, 0, self.cur_theta_vel)
            self.cmd_publish.publish(twist)
            return False

    def compute_theta(self,target_pose,cur_pose):
        # theta [-180,180]
        # theta = target_pose[1][0]-cur_pose[1][0]
        theta = np.arctan(((target_pose[0][1]-cur_pose[0][1])/(target_pose[0][0]-cur_pose[0][0])))

        if target_pose[0][0]-cur_pose[0][0]<0:
            if theta<0:
                theta = np.pi+theta
            else:
                theta = -np.pi+theta
        theta = theta- cur_pose[1][0]
        theta = (theta+2*np.pi)%(np.pi*2)
        if theta>np.pi:
            theta = theta-2*np.pi

        dis = np.linalg.norm(np.array(target_pose[0])[:2]-np.array(cur_pose[0])[:2])
        return theta,dis

if __name__ == '__main__':
    main()
