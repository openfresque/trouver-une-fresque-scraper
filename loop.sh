#!zsh
while true
do
    python -m trouver_une_fresque_scraper.scrape --skip-dirty-check
    if [ $? != 0 ]; then  # if the command fails (returns a non-zero exit code)
        echo "Command failed, retrying..."
        sleep 5  # wait for 5 seconds before retrying
    else
        break  # if the command succeeds, exit the loop
    fi
done
