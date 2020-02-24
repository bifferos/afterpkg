#!/bin/bash


# Create the mongo group
if grep -q "^mongo:" /etc/group ; then
  echo "mongo group exists, no need to add it"
else
  echo "Creating mongo group"
  groupadd -r -g 285 mongo
fi


# Create the mongo user
if grep -q "^mongo:" /etc/passwd ; then
  echo "mongo user exists, no need to add it"
else
  echo "Creating mongo user"
  useradd -u 285 -d /var/lib/mongodb -s /bin/false -g mongo mongo
fi

