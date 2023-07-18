import configparser


class Attic:
    ''' storage for junk that might be useful someday '''

    def conf(self):
        ''' This will probably never be used '''
        config = configparser.ConfigParser()
        config.read('OreSat0.cfg')
        print(config['main']['rf_samp_rate'])
