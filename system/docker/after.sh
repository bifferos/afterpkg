#/bin/sh

# Create the docker group
if grep -q "^docker:" /etc/group ; then
  echo "docker group exists, no need to add it"
else
  echo "Creating docker group"
  groupadd -r -g 281 docker
fi


# Add all normal users to the docker group.
USER_GID=$(cat /etc/group | grep "^users\:" | cut -d ":" -f 3)
INTERACTIVE_USERS=$(cat /etc/passwd | cut -d ":" -f 1,4 | grep ":$USER_GID$" | cut -d : -f 1 | grep -v "^g
for user in $INTERACTIVE_USERS
do
  DOCKER_USERS=$(cat /etc/group | grep "^docker:" | cut -d : -f 4)
  DOCKER_USERS=",${DOCKER_USERS},"
  if [[ "${DOCKER_USERS}" =~ ",${user}," ]] ; then
    echo "User ${user} already in docker group"
  else
    echo "Adding user ${user} to group docker"
    usermod -a -G docker $user
  fi
done
