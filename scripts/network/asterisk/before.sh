

# Create the asterisk group
if grep -q "^asterisk:" /etc/group ; then
  echo "asterisk group exists, no need to add it"
else
  echo "Creating asterisk group"
  groupadd -g 267 asterisk
fi


# Create the asterisk user
if grep -q "^asterisk:" /etc/passwd ; then
  echo "asterisk user exists, no need to add it"
else
  echo "Creating asterisk user"
  useradd -u 267 -d /var/lib/asterisk -s /bin/false -g asterisk asterisk
fi

