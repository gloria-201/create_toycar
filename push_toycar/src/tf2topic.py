#!/usr/bin/python2
# -*- coding: utf-8 -*-
#  publish tf from laser to map

import tf
import rospy
from create_msgs.msg import laser2map
from std_msgs.msg import Header
from tf.transformations import quaternion_matrix


def main():
    rospy.init_node("laser2map")
    pub = rospy.Publisher('laser2map', laser2map, queue_size=1)
    listener = tf.TransformListener()
    cur_index = 0
    r = rospy.Rate(20)

    while not rospy.is_shutdown():
        try:
            (trans, rot) = listener.lookupTransform('/map', '/laser', rospy.Time(0))
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            continue
        header = Header(cur_index, rospy.Time.now(), 'laser2map')
        R = quaternion_matrix(rot)[:3, :3]
        pub.publish(laser2map(header=header, R=R.flatten().tolist(), T=trans))
        cur_index += 1
        r.sleep()


if __name__ == '__main__':
    main()
